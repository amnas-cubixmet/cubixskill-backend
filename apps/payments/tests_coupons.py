from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from payments.models import Coupon, CouponScope, DiscountType, PaymentContext
from payments.services import CouponService, PaymentPricingService

class CourseCouponsTestCase(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy")
        self.course = Course.objects.create(title="React Masterclass", academy=self.academy, price=Decimal('5000.00'))
        self.student = User.objects.create(email="student@example.com", full_name="Student Test")

    def test_create_percentage_coupon_and_calculate_discount(self):
        coupon = Coupon.objects.create(
            code="WELCOME20",
            name="Welcome 20%",
            scope=CouponScope.ACADEMY_COURSE,
            academy=self.academy,
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal('20.00'),
            minimum_order_amount=Decimal('1000.00')
        )
        coupon.courses.add(self.course)

        pricing = PaymentPricingService.calculate_order_pricing(
            subtotal_amount=Decimal('5000.00'),
            coupon_code="WELCOME20",
            academy=self.academy,
            course=self.course
        )

        self.assertEqual(pricing['subtotal'], Decimal('5000.00'))
        self.assertEqual(pricing['discount'], Decimal('1000.00'))
        self.assertEqual(pricing['final_amount'], Decimal('4000.00'))

    def test_fixed_amount_coupon_discount(self):
        coupon = Coupon.objects.create(
            code="SAVE500",
            name="Save 500",
            scope=CouponScope.ACADEMY_COURSE,
            academy=self.academy,
            discount_type=DiscountType.FIXED_AMOUNT,
            discount_value=Decimal('500.00')
        )
        coupon.courses.add(self.course)

        pricing = PaymentPricingService.calculate_order_pricing(
            subtotal_amount=Decimal('5000.00'),
            coupon_code="SAVE500",
            academy=self.academy,
            course=self.course
        )

        self.assertEqual(pricing['discount'], Decimal('500.00'))
        self.assertEqual(pricing['final_amount'], Decimal('4500.00'))

    def test_expired_coupon_raises_validation_error(self):
        past_date = timezone.now() - timezone.timedelta(days=2)
        coupon = Coupon.objects.create(
            code="EXPIRED10",
            name="Expired Promo",
            scope=CouponScope.ACADEMY_COURSE,
            academy=self.academy,
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal('10.00'),
            valid_until=past_date
        )
        coupon.courses.add(self.course)

        with self.assertRaises(ValidationError):
            CouponService.validate_coupon(
                code="EXPIRED10",
                user=self.student,
                payment_context=PaymentContext.COURSE_PURCHASE,
                academy=self.academy,
                course=self.course,
                order_amount=Decimal('5000.00')
            )

    def test_usage_limit_reached_raises_validation_error(self):
        coupon = Coupon.objects.create(
            code="LIMIT1",
            name="Single Use Promo",
            scope=CouponScope.ACADEMY_COURSE,
            academy=self.academy,
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal('10.00'),
            total_usage_limit=1,
            current_usage_count=1
        )
        coupon.courses.add(self.course)

        with self.assertRaises(ValidationError):
            CouponService.validate_coupon(
                code="LIMIT1",
                user=self.student,
                payment_context=PaymentContext.COURSE_PURCHASE,
                academy=self.academy,
                course=self.course,
                order_amount=Decimal('5000.00')
            )
