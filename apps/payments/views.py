import uuid
from decimal import Decimal
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied

from courses.models import Course
from plans_entitlements.models import Plan, AddOn
from enrollments.services import EnrollmentService
from payments.models import (
    Coupon,
    PaymentOrder,
    CouponScope,
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

