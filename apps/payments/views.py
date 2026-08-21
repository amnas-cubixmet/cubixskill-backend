import uuid
import random
import string
from decimal import Decimal
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
from payments.models import (
    Coupon,
    CouponRedemption,
    PaymentOrder,
    CouponScope,
    DiscountType,
    PaymentContext,
)
from payments.selectors import PaymentSelector
from payments.services import (
    PaymentOrderService,
    PaymentPricingService,
    PaymentFulfillmentService,
    PaymentGatewayService,
)
from payments.serializers import (
    CouponSerializer,
    CreateCouponSerializer,
    ValidateCouponSerializer,
    CourseCheckoutSerializer,
    PlatformCheckoutSerializer,
    PayOrderSerializer,
    PaymentOrderSerializer,
    CouponRedemptionSerializer,
)

# --------------------------------------------------------------
# 1. Course Checkout & Pay API
# --------------------------------------------------------------

class CourseCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)

        # Free course check (Requirement #27: no fake gateway transaction needed)
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

# --------------------------------------------------------------
# 2. Coupon Validation Preview Endpoint
# --------------------------------------------------------------

class ValidateCouponView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ValidateCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course = None
        academy = None
        if data.get('course_id'):
            course = get_object_or_404(Course, id=data['course_id'])
            academy = course.academy

        subtotal = Decimal(str(course.price)) if course else Decimal('100.00')

        pricing = PaymentPricingService.calculate_order_pricing(
            subtotal_amount=subtotal,
            coupon_code=data['coupon_code'],
            user=request.user,
            payment_context=data['payment_context'],
            academy=academy,
            course=course
        )

        return Response({
            "valid": True,
            "coupon_code": data['coupon_code'],
            "subtotal": str(pricing['subtotal']),
            "discount": str(pricing['discount']),
            "total": str(pricing['final_amount']),
            "currency": "INR"
        }, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 3. Platform Checkout Endpoint (Academy Admin / Staff)
# --------------------------------------------------------------

class PlatformCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        academy = getattr(request.user, 'academy', None)
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

# --------------------------------------------------------------
# 4. Student Payment History ViewSet
# --------------------------------------------------------------

class StudentPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PaymentSelector.get_student_payment_history(self.request.user)

# --------------------------------------------------------------
# 5. Academy Payment History ViewSet
# --------------------------------------------------------------

class AcademyPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy:
            return PaymentOrder.objects.none()
        return PaymentSelector.get_academy_payment_history(academy)

# --------------------------------------------------------------
# 6. Super Admin Payment History ViewSet
# --------------------------------------------------------------

class AdminPaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return PaymentSelector.get_admin_payment_history(
            status=self.request.query_params.get('status'),
            payment_context=self.request.query_params.get('payment_context')
        )

# --------------------------------------------------------------
# 7. Academy Coupon Management ViewSet
# --------------------------------------------------------------

class AcademyCouponViewSet(viewsets.ModelViewSet):
    serializer_class = CouponSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy:
            return Coupon.objects.none()
        return Coupon.objects.filter(academy=academy, scope=CouponScope.ACADEMY_COURSE)

    def create(self, request, *args, **kwargs):
        academy = getattr(request.user, 'academy', None)
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


# --------------------------------------------------------------
# 7B. Course-Level Coupon REST API Views
# --------------------------------------------------------------

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

# --------------------------------------------------------------
# 8. Admin Platform Coupon ViewSet (Super Admin)
# --------------------------------------------------------------

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

# --------------------------------------------------------------
# 9. Payment Webhooks
# Processes authenticated provider callbacks idempotently.
# Verify the provider webhook signature before trusting payload data.
# Provider retries may deliver the same event more than once.
# Webhook processing must therefore be idempotent.
# --------------------------------------------------------------

class PaymentWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, gateway):
        payload_body = request.body.decode('utf-8') if request.body else request.data
        headers = dict(request.headers)

        PaymentFulfillmentService.handle_webhook_event(
            gateway=gateway,
            headers=headers,
            raw_body=payload_body
        )

        return Response({"status": "received"}, status=status.HTTP_200_OK)

