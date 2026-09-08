from decimal import Decimal

from academy.models import Academy
from courses.models import Course, CourseStatus
from django.test import TestCase
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus
from payments.models import (
    Coupon,
    CouponRedemption,
    CouponScope,
    DiscountType,
    OrderStatus,
    PaymentContext,
    RefundStatus,
)
from payments.services import (
    CouponService,
    PaymentFulfillmentService,
    PaymentOrderService,
    RefundService,
)
from rest_framework.exceptions import ValidationError
from users_roles.models import SystemRoleCode, User


class PaymentsAppTestCase(TestCase):
    def setUp(self):
        # 1. Setup Academy & Users
        self.academy_a = Academy.objects.create(name="Academy Alpha", slug="alpha")
        self.academy_b = Academy.objects.create(name="Academy Beta", slug="beta")

        from credits.models import CreditAccount
        CreditAccount.objects.get_or_create(academy=self.academy_a, defaults={'balance': Decimal('1000.00')})
        CreditAccount.objects.get_or_create(academy=self.academy_b, defaults={'balance': Decimal('1000.00')})

        self.student = User.objects.create_user(
            email="student@example.com",
            full_name="Jane Student",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy_a
        )

        self.academy_admin = User.objects.create_user(
            email="admin@alpha.com",
            full_name="Admin Alpha",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy_a
        )

        # 2. Setup Courses
        self.course_paid = Course.objects.create(
            academy=self.academy_a,
            title="Python Masterclass",
            slug="python-masterclass",
            price=Decimal('1000.00'),
            is_free=False,
            status=CourseStatus.PUBLISHED
        )

        self.course_free = Course.objects.create(
            academy=self.academy_a,
            title="Intro to Programming",
            slug="intro-prog",
            price=Decimal('0.00'),
            is_free=True,
            status=CourseStatus.PUBLISHED
        )

        self.course_academy_b = Course.objects.create(
            academy=self.academy_b,
            title="Beta Course",
            slug="beta-course",
            price=Decimal('500.00'),
            is_free=False,
            status=CourseStatus.PUBLISHED
        )

        # 3. Setup Coupons
        self.academy_coupon = Coupon.objects.create(
            code="ALPHA200",
            name="Alpha 200 Off",
            scope=CouponScope.ACADEMY_COURSE,
            academy=self.academy_a,
            discount_type=DiscountType.FIXED_AMOUNT,
            discount_value=Decimal('200.00'),
            valid_from=timezone.now() - timezone.timedelta(days=1),
            valid_until=timezone.now() + timezone.timedelta(days=10),
            total_usage_limit=10,
            is_active=True
        )

        self.platform_coupon = Coupon.objects.create(
            code="PLATFORM100",
            name="Platform 100 Off",
            scope=CouponScope.PLATFORM,
            academy=None,
            discount_type=DiscountType.FIXED_AMOUNT,
            discount_value=Decimal('100.00'),
            valid_from=timezone.now() - timezone.timedelta(days=1),
            valid_until=timezone.now() + timezone.timedelta(days=10),
            total_usage_limit=5,
            is_active=True
        )

    def test_course_checkout_pricing_and_fulfillment(self):
        """
        Tests student course checkout, discount calculation, payment fulfillment, and enrollment creation.
        """
        # Create Payment Order
        order, gw_data = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            coupon_code="ALPHA200",
            gateway="RAZORPAY"
        )

        self.assertEqual(order.subtotal_amount, Decimal('1000.00'))
        self.assertEqual(order.discount_amount, Decimal('200.00'))
        self.assertEqual(order.final_amount, Decimal('800.00'))
        self.assertEqual(order.academy, self.academy_a)

        # Fulfill Payment
        completed_order = PaymentFulfillmentService.process_successful_payment(
            order=order,
            gateway_payment_id="pay_test_123456",
            gateway="RAZORPAY",
            payment_method="UPI"
        )

        self.assertEqual(completed_order.status, OrderStatus.COMPLETED)

        # Verify Enrollment
        is_enrolled = Enrollment.objects.filter(
            student=self.student,
            course=self.course_paid,
            status=EnrollmentStatus.ACTIVE
        ).exists()
        self.assertTrue(is_enrolled)

        # Verify Coupon Redemption & Usage Count
        self.academy_coupon.refresh_from_db()
        self.assertEqual(self.academy_coupon.current_usage_count, 1)
        self.assertTrue(CouponRedemption.objects.filter(coupon=self.academy_coupon, order=order).exists())

        # Verify Invoice
        self.assertTrue(hasattr(completed_order, 'invoice'))
        self.assertEqual(completed_order.invoice.total_amount, Decimal('800.00'))

    def test_coupon_scope_and_isolation_rules(self):
        """
        Tests that platform coupons cannot be used for course checkout and academy coupons cannot cross tenant boundaries.
        """
        # 1. Platform coupon on course checkout must fail
        with self.assertRaises(ValidationError):
            CouponService.validate_coupon(
                code="PLATFORM100",
                user=self.student,
                payment_context=PaymentContext.COURSE_PURCHASE,
                academy=self.academy_a,
                course=self.course_paid,
                order_amount=Decimal('1000.00')
            )

        # 2. Academy A coupon on Academy B course must fail
        with self.assertRaises(ValidationError):
            CouponService.validate_coupon(
                code="ALPHA200",
                user=self.student,
                payment_context=PaymentContext.COURSE_PURCHASE,
                academy=self.academy_b,
                course=self.course_academy_b,
                order_amount=Decimal('500.00')
            )

    def test_idempotent_webhook_and_fulfillment(self):
        """
        Tests that duplicate webhook invocations do not cause duplicate fulfillment or errors.
        """
        order, _ = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            gateway="RAZORPAY"
        )

        payload = {
            "order_id": str(order.id),
            "payment_id": "pay_webhook_999"
        }

        # First webhook dispatch
        res1 = PaymentFulfillmentService.handle_webhook_event(
            event_id="evt_001",
            gateway="RAZORPAY",
            event_type="order.paid",
            payload=payload,
            signature_valid=True
        )
        self.assertTrue(res1)

        # Second duplicate webhook dispatch
        res2 = PaymentFulfillmentService.handle_webhook_event(
            event_id="evt_001",
            gateway="RAZORPAY",
            event_type="order.paid",
            payload=payload,
            signature_valid=True
        )
        self.assertTrue(res2)

        # Check single enrollment
        enrollment_count = Enrollment.objects.filter(student=self.student, course=self.course_paid).count()
        self.assertEqual(enrollment_count, 1)

    def test_refund_processing(self):
        """
        Tests processing full refund on a completed order.
        """
        order, _ = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            gateway="RAZORPAY"
        )

        completed_order = PaymentFulfillmentService.process_successful_payment(
            order=order,
            gateway_payment_id="pay_refund_target",
            gateway="RAZORPAY"
        )

        tx = completed_order.transactions.first()
        refund = RefundService.process_refund(
            transaction_obj=tx,
            refund_amount=Decimal('1000.00'),
            reason="Student requested refund"
        )

        self.assertEqual(refund.status, RefundStatus.SUCCESS)
        completed_order.refresh_from_db()
        self.assertEqual(completed_order.status, OrderStatus.REFUNDED)

    def test_razorpay_provider_checkout_and_verification(self):
        """
        Tests Razorpay adapter order creation and payment signature verification.
        """
        from payments.providers.factory import PaymentProviderFactory
        from payments.providers.razorpay_provider import RazorpayProvider

        provider = PaymentProviderFactory.get_provider('razorpay')
        self.assertIsInstance(provider, RazorpayProvider)

        # Create Order via Razorpay
        order, gw_data = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            gateway="RAZORPAY"
        )

        self.assertEqual(order.gateway, "RAZORPAY")
        self.assertTrue(order.gateway_order_id.startswith("order_"))
        self.assertEqual(gw_data['gateway'], "RAZORPAY")
        self.assertIn("gateway_order_id", gw_data)

        # Verify Payment via Razorpay Provider
        ver_res = provider.verify_payment({
            'razorpay_order_id': order.gateway_order_id,
            'razorpay_payment_id': 'pay_test_rzp_123',
            'razorpay_signature': 'mock_sig_valid'
        })

        self.assertTrue(ver_res['is_success'])
        self.assertEqual(ver_res['gateway_payment_id'], 'pay_test_rzp_123')

    def test_razorpay_webhook_parsing_and_idempotent_fulfillment(self):
        """
        Tests parsing Razorpay webhook payloads and performing idempotent business fulfillment.
        """
        order, _ = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            gateway="RAZORPAY"
        )

        razorpay_payload = {
            "entity": "event",
            "account_id": "acc_rzp_001",
            "event": "payment.captured",
            "created_at": 1600000000,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_rzp_fulfilled_999",
                        "order_id": order.gateway_order_id,
                        "amount": 100000,
                        "currency": "INR",
                        "notes": {
                            "order_id": str(order.id),
                            "order_number": order.order_number
                        }
                    }
                }
            }
        }

        # Dispatch Razorpay Webhook
        res1 = PaymentFulfillmentService.handle_webhook_event(
            gateway="razorpay",
            payload=razorpay_payload,
            signature_valid=True
        )
        self.assertTrue(res1)

        # Verify Order completed & Student Enrolled
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.course_paid).exists())

        # Duplicate Webhook Dispatch
        res2 = PaymentFulfillmentService.handle_webhook_event(
            gateway="razorpay",
            payload=razorpay_payload,
            signature_valid=True
        )
        self.assertTrue(res2)
        self.assertEqual(Enrollment.objects.filter(student=self.student, course=self.course_paid).count(), 1)

    def test_razorpay_refund_processing(self):
        """
        Tests refund execution using Razorpay provider.
        """
        order, _ = PaymentOrderService.create_payment_order(
            payment_context=PaymentContext.COURSE_PURCHASE,
            payer=self.student,
            course=self.course_paid,
            gateway="RAZORPAY"
        )

        completed_order = PaymentFulfillmentService.process_successful_payment(
            order=order,
            gateway_payment_id="pay_rzp_refund_target",
            gateway="RAZORPAY"
        )

        tx = completed_order.transactions.first()
        refund = RefundService.process_refund(
            transaction_obj=tx,
            refund_amount=Decimal('1000.00'),
            reason="Customer request"
        )

        self.assertEqual(refund.status, RefundStatus.SUCCESS)
        self.assertTrue(refund.gateway_refund_id.startswith("rfnd_"))
        completed_order.refresh_from_db()
        self.assertEqual(completed_order.status, OrderStatus.REFUNDED)

    def test_create_payment_order_api(self):
        """
        Tests POST /api/v1/payments/orders/ API creates order and returns 201.
        """
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.student)

        url = '/api/v1/payments/orders/'
        payload = {
            'academy_uuid': str(self.academy_a.pk),
            'course_uuid': str(self.course_paid.id),
        }

        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['success'])
        self.assertIn('order', response.data)
        self.assertIn('razorpay_order_id', response.data['order'])


