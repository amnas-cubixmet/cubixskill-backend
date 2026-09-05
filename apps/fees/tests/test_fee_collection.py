from decimal import Decimal
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from users_roles.models import User
from academy.models import Academy
from courses.models import Course
from enrollments.models import Enrollment, EnrollmentStatus
from fees.models import (
    StudentFeeAccount,
    StudentFeeAccountStatus,
    FeeInstallment,
    InstallmentStatus,
    FeePayment,
)
from fees.services import FeeAccountService, FeeCollectionService
from payments.models import AcademySettlement, SettlementStatus


class FeeCollectionTestCase(TestCase):

    def setUp(self):
        self.academy_a = Academy.objects.create(name="Academy Alpha", slug="academy-alpha")
        self.academy_b = Academy.objects.create(name="Academy Beta", slug="academy-beta")

        self.course_a = Course.objects.create(
            academy=self.academy_a,
            title="Python Masterclass",
            slug="python-masterclass",
            price=Decimal('5000.00'),
            sale_price=Decimal('5000.00')
        )

        self.student = User.objects.create(
            email="student1@example.com",
            full_name="Alice Student",
            is_active=True
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course_a,
            student=self.student,
            status=EnrollmentStatus.ACTIVE
        )

    def test_canonical_course_price_snapshot(self):
        """
        Verify StudentFeeAccount snapshots Course.price (₹5000) automatically without trusting user inputs.
        """
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course_a,
            plan_type='ONE_TIME'
        )
        self.assertEqual(account.total_fee_amount, Decimal('5000.00'))
        self.assertEqual(account.effective_fee_amount, Decimal('5000.00'))
        self.assertEqual(account.status, StudentFeeAccountStatus.UNPAID)

    def test_partial_and_complete_payments(self):
        """
        Verify partial payments update paid amount and balance, and full payment sets PAID status.
        """
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course_a,
            plan_type='MONTHLY',
            number_of_installments=5
        )

        # 1. Pay ₹1000
        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('1000.00'),
            collection_mode='DIRECT_ACADEMY',
            payment_method='UPI'
        )
        account.refresh_from_db()
        payments = FeePayment.objects.filter(fee_account=account, status='COMPLETED')
        paid_sum = sum(p.amount for p in payments)
        self.assertEqual(paid_sum, Decimal('1000.00'))
        self.assertEqual(account.effective_fee_amount - paid_sum, Decimal('4000.00'))
        self.assertIn(account.status, [StudentFeeAccountStatus.PARTIALLY_PAID, StudentFeeAccountStatus.PARTIAL])

        # 2. Pay ₹2000
        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('2000.00'),
            collection_mode='DIRECT_ACADEMY',
            payment_method='UPI'
        )
        account.refresh_from_db()
        paid_sum = sum(p.amount for p in account.payments.filter(status='COMPLETED'))
        self.assertEqual(paid_sum, Decimal('3000.00'))
        self.assertEqual(account.effective_fee_amount - paid_sum, Decimal('2000.00'))

        # 3. Complete remaining ₹2000
        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('2000.00'),
            collection_mode='DIRECT_ACADEMY',
            payment_method='UPI'
        )
        account.refresh_from_db()
        paid_sum = sum(p.amount for p in account.payments.filter(status='COMPLETED'))
        self.assertEqual(paid_sum, Decimal('5000.00'))
        self.assertEqual(account.effective_fee_amount - paid_sum, Decimal('0.00'))
        self.assertEqual(account.status, StudentFeeAccountStatus.PAID)

    def test_overpayment_rejection(self):
        """
        Verify payment exceeding payable balance is rejected with ValidationError.
        """
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course_a,
            plan_type='ONE_TIME'
        )

        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('3000.00')
        )
        account.refresh_from_db()

        # Attempt to pay ₹2500 when balance is ₹2000
        with self.assertRaises(ValidationError):
            FeeCollectionService.record_payment(
                fee_account=account,
                amount=Decimal('2500.00')
            )

    def test_direct_upi_vs_razorpay_gateway_settlement(self):
        """
        Direct Academy UPI produces NO platform settlement liability.
        CubixSkill Razorpay Gateway produces platform settlement liability.
        """
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course_a,
            plan_type='ONE_TIME'
        )

        # Direct Academy payment of ₹1000
        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('1000.00'),
            collection_mode='DIRECT_ACADEMY',
            payment_method='UPI'
        )
        self.assertEqual(AcademySettlement.objects.filter(academy=self.academy_a).count(), 0)

        # Razorpay Gateway payment of ₹1000
        FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('1000.00'),
            collection_mode='CUBIXSKILL_GATEWAY',
            payment_method='UPI',
            gateway_order_id='order_test_123',
            gateway_payment_id='pay_test_123'
        )
        self.assertEqual(AcademySettlement.objects.filter(academy=self.academy_a).count(), 1)
        settlement = AcademySettlement.objects.filter(academy=self.academy_a).first()
        self.assertEqual(settlement.gross_amount, Decimal('1000.00'))
        self.assertEqual(settlement.status, SettlementStatus.PENDING)

    def test_duplicate_gateway_webhook_idempotency(self):
        """
        Duplicate payment notification for same gateway_payment_id returns existing record without duplicating.
        """
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course_a,
            plan_type='ONE_TIME'
        )

        p1 = FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('1000.00'),
            collection_mode='CUBIXSKILL_GATEWAY',
            gateway_payment_id='pay_dup_001'
        )

        p2 = FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('1000.00'),
            collection_mode='CUBIXSKILL_GATEWAY',
            gateway_payment_id='pay_dup_001'
        )

        self.assertEqual(p1.id, p2.id)
        self.assertEqual(FeePayment.objects.filter(gateway_payment_id='pay_dup_001').count(), 1)

