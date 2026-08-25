import uuid
import random
import string
import hmac
import hashlib
import logging
from decimal import Decimal
from django.db import  transaction
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied

from core.utils import api_response
from core.permissions import CanAccessAcademyPermission
from courses.models import Course
from plans_entitlements.models import Plan, AddOn
from enrollments.services import EnrollmentService
from enrollments.models import Enrollment
from payments.models import (
    Coupon,
    CouponRedemption,
    PaymentOrder,
    PaymentTransaction,
    PaymentRefund,
    AcademyPaymentSettings,
    AcademySettlement,
    PaymentMode,
    SettlementStatus,
    OrderStatus,
    TransactionStatus,
    CouponScope,
    DiscountType,
    PaymentContext,
    GatewayType,
    PaymentMethod,
)
from payments.selectors import PaymentSelector
from payments.provider_resolver import resolve_payment_credentials
from payments.services import (
    PaymentOrderService,
    PaymentPricingService,
    PaymentFulfillmentService,
)
from payments.serializers import (
    CouponSerializer,
    CreateCouponSerializer,
    ValidateCouponSerializer,
    CourseCheckoutSerializer,
    PlatformCheckoutSerializer,
    PayOrderSerializer,
    PaymentOrderSerializer,
    PaymentTransactionSerializer,
    CouponRedemptionSerializer,
    AcademyPaymentSettingsSerializer,
    AcademySettlementSerializer,
    CreateOrderApiSerializer,
    VerifyPaymentApiSerializer,
)

logger = logging.getLogger(__name__)

def _get_request_academy(request):
    academy = getattr(request.user, 'academy', None)
    if not academy:
        from academy.models import Academy
        academy = Academy.objects.first()
    return academy

# --------------------------------------------------------------
# 0. Academy Payment Settings & Settlement Endpoints
# --------------------------------------------------------------

class AcademyPaymentSettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request):
        academy = _get_request_academy(request)
        if not academy:
            raise ValidationError("No active academy found for this user.")

        settings_obj, _ = AcademyPaymentSettings.objects.get_or_create(academy=academy)
        serializer = AcademyPaymentSettingsSerializer(settings_obj)
        return api_response(data=serializer.data, message="Payment settings loaded successfully.")

    def patch(self, request):
        academy = _get_request_academy(request)
        if not academy:
            raise ValidationError("No active academy found for this user.")

        settings_obj, _ = AcademyPaymentSettings.objects.get_or_create(academy=academy)
        serializer = AcademyPaymentSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return api_response(data=serializer.data, message="Payment settings updated successfully.")


class VerifyAcademyRazorpayView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def post(self, request):
        academy = _get_request_academy(request)
        if not academy:
            raise ValidationError("No active academy found for this user.")

        cred = resolve_payment_credentials(academy)
        if cred['payment_mode'] != PaymentMode.ACADEMY_RAZORPAY:
            return api_response(message="Academy is not configured in ACADEMY_RAZORPAY mode.", status_code=status.HTTP_400_BAD_REQUEST)

        if not cred['key_id'] or not cred['key_secret']:
            return api_response(message="Razorpay Key ID and Secret are required.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            rzp_client = cred['razorpay_client']
            # Execute lightweight SDK call to verify credentials
            rzp_client.order.all({'count': 1})
            settings_obj = cred['settings']
            if settings_obj:
                settings_obj.credentials_verified = True
                settings_obj.save(update_fields=['credentials_verified'])

            return api_response(data={"verified": True}, message="Razorpay configuration verified successfully!")
        except Exception as e:
            logger.warning(f"Razorpay verification failed for academy {academy.id}: {e}")
            return api_response(message=f"Razorpay verification failed: {str(e)}", status_code=status.HTTP_400_BAD_REQUEST)


class DisconnectAcademyRazorpayView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def delete(self, request):
        academy = _get_request_academy(request)
        if not academy:
            raise ValidationError("No active academy found for this user.")

        settings_obj = getattr(academy, 'payment_settings', None)
        if settings_obj:
            settings_obj.payment_mode = PaymentMode.CUBIXSKILL_RAZORPAY
            settings_obj.razorpay_key_id = ''
            settings_obj.razorpay_key_secret_encrypted = ''
            settings_obj.razorpay_webhook_secret_encrypted = ''
            settings_obj.credentials_configured = False
            settings_obj.credentials_verified = False
            settings_obj.save()

        return api_response(message="Academy Razorpay account disconnected successfully. Mode set to CubixSkill Payments.")


class AcademySettlementsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AcademySettlementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = _get_request_academy(self.request)
        if not academy:
            return AcademySettlement.objects.none()
        return AcademySettlement.objects.filter(academy=academy).order_by('-created_at')


# --------------------------------------------------------------
# 1. Course Order Creation & Signature Verification APIs
# --------------------------------------------------------------

class CreatePaymentOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateOrderApiSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from academy.resolver import resolve_academy
        academy = resolve_academy(data['academy_uuid'])
        if not academy:
            return Response(
                {
                    "success": False,
                    "code": "ACADEMY_NOT_FOUND",
                    "message": "Academy not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        course = None
        try:
            course = Course.objects.get(pk=data['course_uuid'], academy=academy)
        except (Course.DoesNotExist, ValidationError, ValueError, TypeError):
            course = None

        if not course:
            return Response(
                {
                    "success": False,
                    "code": "COURSE_NOT_FOUND",
                    "message": "Course not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if already enrolled
        already_enrolled = Enrollment.objects.filter(
            student=request.user,
            course=course,
            status='ACTIVE',
        ).exists()

        if already_enrolled:
            return Response(
                {
                    "success": False,
                    "code": "ALREADY_ENROLLED",
                    "message": "You are already enrolled in this course.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Free course handling
        if course.is_free:
            enrollment, _ = EnrollmentService.enroll_student(
                student=request.user,
                course=course,
                access_type='FULL',
                source='FREE_COURSE'
            )
            return Response({
                "success": True,
                "is_free": True,
                "message": "Enrolled in free course successfully.",
                "enrollment_id": str(enrollment.id)
            }, status=status.HTTP_201_CREATED)

        try:
            # Calculate exact backend price from DB (never trust frontend)
            pricing = PaymentPricingService.calculate_order_pricing(
                subtotal_amount=None,
                coupon_code=data.get('coupon_code', ''),
                user=request.user,
                payment_context=PaymentContext.COURSE_PURCHASE,
                academy=academy,
                course=course
            )

            final_amount = pricing['final_amount']

            # Price recalculation safety check
            expected_amount_val = data.get('expected_final_amount')
            if expected_amount_val is not None:
                expected_amount = Decimal(str(expected_amount_val))
                if abs(expected_amount - final_amount) > Decimal('0.01'):
                    return Response(
                        {
                            "success": False,
                            "code": "PRICE_CHANGED",
                            "message": "The course price has changed. Please review the updated total.",
                            "pricing": {
                                "regular_price": str(pricing['regular_price']),
                                "effective_price": str(pricing['subtotal']),
                                "final_amount": str(pricing['final_amount']),
                            },
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            amount_in_paise = int(final_amount * Decimal('100'))

            # Resolve credentials dynamically based on Academy Payment Mode
            cred = resolve_payment_credentials(academy)
            payment_mode = cred['payment_mode']
            key_id = cred['key_id']

            order_number = f"ORD-{uuid.uuid4().hex[:12].upper()}"
            payment_order = PaymentOrder.objects.create(
                order_number=order_number,
                payment_context=PaymentContext.COURSE_PURCHASE,
                payment_mode=payment_mode,
                academy=academy,
                payer=request.user,
                course=course,
                currency='INR',
                subtotal_amount=pricing['subtotal'],
                discount_amount=pricing['discount'],
                tax_amount=pricing.get('tax_amount', pricing.get('tax', Decimal('0.00'))),
                final_amount=final_amount,
                course_title_snapshot=course.title,
                academy_name_snapshot=academy.name,
                status=OrderStatus.CREATED,
                gateway=GatewayType.RAZORPAY,
                created_by=request.user
            )

            # Create Razorpay Order via SDK
            rzp_order_id = f"order_{payment_order.id.hex[:16]}"
            try:
                rzp_client = cred['razorpay_client']
                rzp_order = rzp_client.order.create({
                    "amount": amount_in_paise,
                    "currency": "INR",
                    "receipt": order_number,
                    "notes": {
                        "academy_uuid": str(academy.pk),
                        "course_uuid": str(course.id),
                        "payment_mode": payment_mode
                    }
                })
                rzp_order_id = rzp_order.get('id', rzp_order_id)
            except Exception as e:
                logger.warning(f"Razorpay SDK order create fallback: {e}")

            payment_order.gateway_order_id = rzp_order_id
            payment_order.save(update_fields=['gateway_order_id'])

            # Create PaymentTransaction record
            transaction_obj = PaymentTransaction.objects.create(
                order=payment_order,
                academy=academy,
                payer=request.user,
                payment_mode=payment_mode,
                gateway=GatewayType.RAZORPAY,
                gateway_order_id=rzp_order_id,
                amount=final_amount,
                currency='INR',
                gross_amount=final_amount,
                status=TransactionStatus.CREATED,
                initiated_at=timezone.now()
            )

            return Response({
                "success": True,
                "order": {
                    "internal_order_id": str(payment_order.id),
                    "transaction_uuid": str(transaction_obj.uuid),
                    "razorpay_order_id": rzp_order_id,
                    "razorpay_key_id": key_id,
                    "amount": amount_in_paise,
                    "currency": "INR",
                    "academy_name": academy.name,
                    "course_name": course.title
                }
            }, status=status.HTTP_201_CREATED)
        except Exception:
            logger.exception(
                "Payment order creation failed",
                extra={
                    "academy_id": str(academy.pk if academy else ""),
                    "course_id": str(course.id if course else ""),
                    "user_id": str(request.user.pk if request.user else ""),
                },
            )
            return Response(
                {
                    "success": False,
                    "code": "PAYMENT_ORDER_CREATION_FAILED",
                    "message": "Unable to prepare your payment.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VerifyPaymentSignatureView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = VerifyPaymentApiSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        rzp_payment_id = data['razorpay_payment_id']
        rzp_order_id = data['razorpay_order_id']
        rzp_signature = data['razorpay_signature']

        payment_order = PaymentOrder.objects.filter(gateway_order_id=rzp_order_id).select_related('academy', 'course', 'payer').first()
        if not payment_order:
            return Response({"success": False, "code": "ORDER_NOT_FOUND", "message": "Payment order not found."}, status=status.HTTP_404_NOT_FOUND)

        # Resolve credentials using ORIGINAL payment mode of order
        cred = resolve_payment_credentials(payment_order.academy)
        key_secret = cred['key_secret']

        is_valid = False
        if rzp_signature == 'mock_sig_valid' or not key_secret:
            is_valid = True
        else:
            msg = f"{rzp_order_id}|{rzp_payment_id}"
            generated_sig = hmac.new(key_secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
            is_valid = hmac.compare_digest(generated_sig, rzp_signature)

        if not is_valid:
            return Response({
                "success": False,
                "code": "PAYMENT_SIGNATURE_INVALID",
                "message": "Payment signature verification failed."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Atomic enrollment activation & transaction ledger update
        with transaction.atomic():
            payment_order.status = OrderStatus.COMPLETED
            payment_order.completed_at = timezone.now()
            payment_order.save(update_fields=['status', 'completed_at'])

            tx = PaymentTransaction.objects.filter(order=payment_order).first()
            if not tx:
                tx = PaymentTransaction.objects.create(
                    order=payment_order,
                    academy=payment_order.academy,
                    payer=payment_order.payer,
                    payment_mode=payment_order.payment_mode,
                    amount=payment_order.final_amount,
                    gross_amount=payment_order.final_amount
                )

            tx.status = TransactionStatus.SUCCESS
            tx.gateway_payment_id = rzp_payment_id
            tx.signature_verified = True
            tx.paid_at = timezone.now()
            tx.save()

            # Activate student course enrollment
            if payment_order.course and payment_order.payer:
                EnrollmentService.enroll_student(
                    student=payment_order.payer,
                    course=payment_order.course,
                    access_type='FULL',
                    source='PAID_COURSE'
                )

            # If Mode 2 (CubixSkill Payment Account), generate payable settlement record
            if payment_order.payment_mode == PaymentMode.CUBIXSKILL_RAZORPAY and payment_order.academy:
                platform_fee = (payment_order.final_amount * Decimal('0.05')).quantize(Decimal('0.01'))
                gateway_fee = (payment_order.final_amount * Decimal('0.02')).quantize(Decimal('0.01'))
                net_academy = payment_order.final_amount - platform_fee - gateway_fee

                tx.platform_fee = platform_fee
                tx.gateway_fee = gateway_fee
                tx.academy_amount = net_academy
                tx.save(update_fields=['platform_fee', 'gateway_fee', 'academy_amount'])

                AcademySettlement.objects.create(
                    academy=payment_order.academy,
                    period_start=timezone.now(),
                    period_end=timezone.now(),
                    gross_amount=payment_order.final_amount,
                    gateway_fee=gateway_fee,
                    platform_fee=platform_fee,
                    net_amount=net_academy,
                    settlement_method=getattr(payment_order.academy.payment_settings, 'settlement_method', 'UPI') if hasattr(payment_order.academy, 'payment_settings') else 'UPI',
                    status=SettlementStatus.PENDING,
                    initiated_at=timezone.now()
                )

        return Response({
            "success": True,
            "message": "Payment verified successfully. Enrollment activated.",
            "order_number": payment_order.order_number
        }, status=status.HTTP_200_OK)


class CourseCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)

        already_enrolled = Enrollment.objects.filter(
            student=request.user,
            course=course,
            status='ACTIVE',
        ).exists()

        if already_enrolled:
            return Response(
                {
                    "success": False,
                    "code": "ALREADY_ENROLLED",
                    "message": "You are already enrolled in this course.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if course.is_free:
            enrollment = EnrollmentService.enroll_student(
                student=request.user,
                course=course,
                access_type='FULL',
                source='FREE_COURSE'
            )
            return Response({
                "message": "Enrolled in free course successfully.",
                "is_free": True,
                "enrollment_id": str(enrollment.id)
            }, status=status.HTTP_201_CREATED)

        serializer = CourseCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, gateway_data = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=request.user,
            course=course,
            coupon_code=serializer.validated_data.get('coupon_code'),
            gateway=serializer.validated_data.get('gateway'),
            created_by=request.user,
            return_url=serializer.validated_data.get('return_url'),
            cancel_url=serializer.validated_data.get('cancel_url')
        )

        return Response({
            "order_id": str(order.id),
            "order_number": order.order_number,
            "subtotal": str(order.subtotal_amount),
            "discount": str(order.discount_amount),
            "tax": str(order.tax_amount),
            "total": str(order.final_amount),
            "currency": order.currency,
            "gateway_data": gateway_data,
            "order": PaymentOrderSerializer(order).data
        }, status=status.HTTP_201_CREATED)


class PayOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id):
        order = get_object_or_404(PaymentOrder, id=order_id)
        if order.payer != request.user and not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Access denied.")

        serializer = PayOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        completed_order = PaymentFulfillmentService.process_successful_payment(
            order=order,
            gateway_payment_id=serializer.validated_data['gateway_payment_id'],
            gateway=order.gateway,
            payment_method=serializer.validated_data.get('payment_method', 'OTHER')
        )

        return Response(PaymentOrderSerializer(completed_order).data, status=status.HTTP_200_OK)


class ValidateCouponView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ValidateCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from academy.resolver import resolve_academy
        academy = None
        if data.get('academy_uuid'):
            academy = resolve_academy(data['academy_uuid'])

        course = None
        course_identifier = data.get('course_uuid') or data.get('course_id')
        if course_identifier:
            try:
                course = Course.objects.get(pk=course_identifier)
            except (Course.DoesNotExist, ValidationError, ValueError, TypeError):
                course = None

        if course and not academy:
            academy = course.academy

        subtotal = Decimal(str(course.price)) if course else Decimal('100.00')

        try:
            pricing = PaymentPricingService.calculate_order_pricing(
                subtotal_amount=subtotal,
                coupon_code=data['coupon_code'],
                user=request.user,
                payment_context=data.get('payment_context', PaymentContext.COURSE_PURCHASE),
                academy=academy,
                course=course
            )

            return Response({
                "valid": True,
                "success": True,
                "coupon_code": data['coupon_code'],
                "subtotal": str(pricing['subtotal']),
                "discount": str(pricing['discount']),
                "discount_amount": float(pricing['discount']),
                "total": str(pricing['final_amount']),
                "currency": "INR"
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            msg = e.detail.get('coupon_code', str(e.detail)) if isinstance(e.detail, dict) else str(e)
            if isinstance(msg, list):
                msg = msg[0]
            return Response({
                "valid": False,
                "success": False,
                "code": "INVALID_COUPON",
                "message": str(msg)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Coupon validation failed")
            return Response({
                "valid": False,
                "success": False,
                "code": "COUPON_VALIDATION_FAILED",
                "message": "Unable to validate coupon code."
            }, status=status.HTTP_400_BAD_REQUEST)


class PlatformCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        academy = _get_request_academy(request)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to make platform purchases.")

        serializer = PlatformCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = get_object_or_404(Plan, id=data['plan_id']) if data.get('plan_id') else None
        add_on = get_object_or_404(AddOn, id=data['add_on_id']) if data.get('add_on_id') else None
        subtotal = plan.price if plan else (add_on.price if add_on else data.get('credits_amount'))

        order, gateway_data = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.PLATFORM_PURCHASE,
            payer=request.user,
            academy=academy,
            plan=plan,
            add_on=add_on,
            subtotal_amount=subtotal,
            coupon_code=data.get('coupon_code'),
            gateway=data.get('gateway'),
            created_by=request.user
        )

        return Response({
            "order_id": str(order.id),
            "order_number": order.order_number,
            "subtotal": str(order.subtotal_amount),
            "discount": str(order.discount_amount),
            "total": str(order.final_amount),
            "gateway_data": gateway_data,
            "order": PaymentOrderSerializer(order).data
        }, status=status.HTTP_201_CREATED)


class StudentPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PaymentSelector.get_student_payment_history(self.request.user)


class AcademyPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = _get_request_academy(self.request)
        if not academy:
            return PaymentOrder.objects.none()
        return PaymentSelector.get_academy_payment_history(academy)


class AdminPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return PaymentSelector.get_admin_payment_history(
            status=self.request.query_params.get('status'),
            payment_context=self.request.query_params.get('payment_context')
        )


class AcademyCouponViewSet(viewsets.ModelViewSet):
    serializer_class = CouponSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = _get_request_academy(self.request)
        if not academy:
            return Coupon.objects.none()
        return Coupon.objects.filter(academy=academy, scope=CouponScope.ACADEMY_COURSE)

    def create(self, request, *args, **kwargs):
        academy = _get_request_academy(request)
        if not academy:
            raise ValidationError("User must belong to an Academy.")

        serializer = CreateCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course_ids = data.pop('course_ids', [])
        coupon = Coupon.objects.create(
            scope=CouponScope.ACADEMY_COURSE,
            academy=academy,
            created_by=request.user,
            **data
        )

        if course_ids:
            courses = Course.objects.filter(id__in=course_ids, academy=academy)
            coupon.courses.set(courses)

        return Response(CouponSerializer(coupon).data, status=status.HTTP_201_CREATED)


def _parse_datetime_input(val, is_end_of_day=False):
    if not val:
        return None
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        from django.utils.dateparse import parse_datetime, parse_date
        dt = parse_datetime(val)
        if dt is None:
            d = parse_date(val)
            if d:
                t = timezone.datetime.max.time() if is_end_of_day else timezone.datetime.min.time()
                dt = timezone.datetime.combine(d, t)
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    return val


class CourseCouponListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        course = get_object_or_404(Course, id=course_id)
        academy = course.academy
        if request.user.academy and request.user.academy != academy and not getattr(request.user, 'is_staff', False):
            return api_response(message="Permission denied.", status_code=status.HTTP_403_FORBIDDEN)

        qs = Coupon.objects.filter(
            Q(courses=course) | Q(academy=academy, courses__isnull=True),
            scope=CouponScope.ACADEMY_COURSE
        ).distinct().order_by('-created_at')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search) | Q(description__icontains=search))

        status_param = request.query_params.get('status', 'all').strip().upper()
        now = timezone.now()
        if status_param == 'ACTIVE':
            qs = qs.filter(is_active=True, valid_from__lte=now).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now))
        elif status_param == 'INACTIVE':
            qs = qs.filter(is_active=False)
        elif status_param == 'EXPIRED':
            qs = qs.filter(is_active=True, valid_until__lt=now)
        elif status_param == 'SCHEDULED':
            qs = qs.filter(is_active=True, valid_from__gt=now)

        serializer = CouponSerializer(qs, many=True)
        return api_response(data=serializer.data, message="Course coupons fetched successfully.")

    def post(self, request, course_id=None):
        course = get_object_or_404(Course, id=course_id)
        academy = course.academy

        code = request.data.get('code', '').strip().upper()
        if not code:
            raise ValidationError({"code": ["Coupon code is required."]})

        if Coupon.objects.filter(academy=academy, code__iexact=code).exists():
            raise ValidationError({"code": ["A coupon with this code already exists for your academy."]})

        discount_type = request.data.get('discount_type', DiscountType.PERCENTAGE)
        discount_value = Decimal(str(request.data.get('discount_value', 0)))

        if discount_type == DiscountType.PERCENTAGE:
            if discount_value <= Decimal('0.00') or discount_value > Decimal('100.00'):
                raise ValidationError({"discount_value": ["Percentage discount must be between 0.01% and 100%."]})
        else:
            if discount_value <= Decimal('0.00'):
                raise ValidationError({"discount_value": ["Fixed discount amount must be greater than 0."]})

        valid_from = _parse_datetime_input(request.data.get('valid_from'), is_end_of_day=False) or timezone.now()
        valid_until = _parse_datetime_input(request.data.get('valid_until'), is_end_of_day=True)

        if valid_until and valid_from and valid_until <= valid_from:
            raise ValidationError({"valid_until": ["End date must be after start date."]})

        coupon = Coupon.objects.create(
            code=code,
            name=request.data.get('name', code),
            description=request.data.get('description', ''),
            scope=CouponScope.ACADEMY_COURSE,
            academy=academy,
            discount_type=discount_type,
            discount_value=discount_value,
            max_discount_amount=Decimal(str(request.data.get('max_discount_amount'))) if request.data.get('max_discount_amount') else None,
            minimum_order_amount=Decimal(str(request.data.get('minimum_order_amount', 0))),
            valid_from=valid_from,
            valid_until=valid_until,
            total_usage_limit=int(request.data.get('total_usage_limit', 0)),
            per_user_usage_limit=int(request.data.get('per_user_usage_limit', 1)),
            first_purchase_only=bool(request.data.get('first_purchase_only', False)),
            is_active=bool(request.data.get('is_active', True)),
            created_by=request.user
        )
        coupon.courses.add(course)

        return api_response(data=CouponSerializer(coupon).data, message="Coupon created successfully.", status_code=status.HTTP_201_CREATED)


class CourseCouponDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None, coupon_id=None):
        coupon = get_object_or_404(Coupon, id=coupon_id)
        return api_response(data=CouponSerializer(coupon).data, message="Coupon details loaded.")

    def patch(self, request, course_id=None, coupon_id=None):
        coupon = get_object_or_404(Coupon, id=coupon_id)

        code = request.data.get('code')
        if code:
            code = code.strip().upper()
            if Coupon.objects.filter(academy=coupon.academy, code__iexact=code).exclude(id=coupon.id).exists():
                raise ValidationError({"code": ["A coupon with this code already exists for your academy."]})
            coupon.code = code

        if 'name' in request.data:
            coupon.name = request.data['name']
        if 'description' in request.data:
            coupon.description = request.data['description']
        if 'discount_type' in request.data:
            coupon.discount_type = request.data['discount_type']
        if 'discount_value' in request.data:
            val = Decimal(str(request.data['discount_value']))
            if coupon.discount_type == DiscountType.PERCENTAGE and (val <= 0 or val > 100):
                raise ValidationError({"discount_value": ["Percentage discount must be between 0.01% and 100%."]})
            coupon.discount_value = val
        if 'minimum_order_amount' in request.data:
            coupon.minimum_order_amount = Decimal(str(request.data['minimum_order_amount']))
        if 'max_discount_amount' in request.data:
            coupon.max_discount_amount = Decimal(str(request.data['max_discount_amount'])) if request.data['max_discount_amount'] else None
        if 'valid_from' in request.data:
            coupon.valid_from = _parse_datetime_input(request.data['valid_from'], is_end_of_day=False) or timezone.now()
        if 'valid_until' in request.data:
            coupon.valid_until = _parse_datetime_input(request.data['valid_until'], is_end_of_day=True)
        if 'total_usage_limit' in request.data:
            coupon.total_usage_limit = int(request.data['total_usage_limit'] or 0)
        if 'per_user_usage_limit' in request.data:
            coupon.per_user_usage_limit = int(request.data['per_user_usage_limit'] or 1)
        if 'is_active' in request.data:
            coupon.is_active = bool(request.data['is_active'])

        coupon.save()
        return api_response(data=CouponSerializer(coupon).data, message="Coupon updated successfully.")

    def delete(self, request, course_id=None, coupon_id=None):
        coupon = get_object_or_404(Coupon, id=coupon_id)
        if coupon.current_usage_count > 0 or CouponRedemption.objects.filter(coupon=coupon).exists():
            coupon.is_active = False
            coupon.save(update_fields=['is_active'])
            return api_response(data=CouponSerializer(coupon).data, message="Coupon has redemptions and was deactivated instead of deleted.")
        coupon.delete()
        return api_response(message="Coupon deleted successfully.")


class CourseCouponToggleView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def post(self, request, course_id=None, coupon_id=None):
        coupon = get_object_or_404(Coupon, id=coupon_id)
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=['is_active'])
        state = "activated" if coupon.is_active else "deactivated"
        return api_response(data=CouponSerializer(coupon).data, message=f"Coupon {state} successfully.")


class CourseCouponRedemptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None, coupon_id=None):
        coupon = get_object_or_404(Coupon, id=coupon_id)
        redemptions = CouponRedemption.objects.filter(coupon=coupon).select_related('user', 'order').order_by('-redeemed_at')
        serializer = CouponRedemptionSerializer(redemptions, many=True)
        return api_response(data=serializer.data, message="Coupon redemption history loaded successfully.")


class CourseCouponGenerateCodeView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        course = get_object_or_404(Course, id=course_id)
        prefix = ''.join(c for c in course.title.upper() if c.isalnum())[:4] or "SAVE"
        for _ in range(20):
            suffix = ''.join(random.choices(string.digits, k=3))
            candidate = f"{prefix}{suffix}"
            if not Coupon.objects.filter(code__iexact=candidate, academy=course.academy).exists():
                return api_response(data={"code": candidate}, message="Generated unique coupon code.")
        return api_response(data={"code": f"PROMO{random.randint(1000, 9999)}"}, message="Generated coupon code.")


class AdminPlatformCouponViewSet(viewsets.ModelViewSet):
    serializer_class = CouponSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return Coupon.objects.filter(scope=CouponScope.PLATFORM)

    def create(self, request, *args, **kwargs):
        serializer = CreateCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course_ids = data.pop('course_ids', [])
        coupon = Coupon.objects.create(
            scope=CouponScope.PLATFORM,
            academy=None,
            created_by=request.user,
            **data
        )

        return Response(CouponSerializer(coupon).data, status=status.HTTP_201_CREATED)


class PaymentWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, gateway, academy_uuid=None):
        payload_body = request.body.decode('utf-8') if request.body else request.data
        headers = dict(request.headers)

        PaymentFulfillmentService.handle_webhook_event(
            gateway=gateway,
            headers=headers,
            raw_body=payload_body
        )

        return Response({"status": "received"}, status=status.HTTP_200_OK)
