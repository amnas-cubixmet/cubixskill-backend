from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
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
from fees.services import FeeAccountService, FeeCollectionService, FeeReminderService
from fees.selectors import FeeCollectionAnalyticsSelector


class FeeCollectionTestCase(TestCase):

    def setUp(self):
        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy")
        self.course = Course.objects.create(
            academy=self.academy,
            title="Test Masterclass",
            slug="test-masterclass",
            price=Decimal('12000.00'),
            sale_price=Decimal('10000.00')
        )
        self.student = User.objects.create(
            email="student_test@example.com",
            full_name="Test Student",
            is_active=True
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
            status=EnrollmentStatus.ACTIVE
        )

    def test_fee_account_configuration_and_installments(self):
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course,
            plan_type='MONTHLY',
            total_fee_amount=Decimal('12000.00'),
            number_of_installments=6
        )
        self.assertEqual(account.status, StudentFeeAccountStatus.PENDING)
        self.assertEqual(account.installments.count(), 6)

    def test_payment_and_waiver_flow(self):
        account = FeeAccountService.configure_student_fee_account(
            student=self.student,
            course=self.course,
            plan_type='MONTHLY',
            total_fee_amount=Decimal('12000.00'),
            number_of_installments=6
        )

        payment1 = FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('4000.00'),
            payment_method='UPI',
            reference_number='UPI-100200'
        )
        account.refresh_from_db()
        self.assertEqual(account.status, StudentFeeAccountStatus.PARTIAL)
        self.assertTrue(payment1.receipt_number.startswith('RCPT-'))

        waiver = FeeCollectionService.waive_fee(
            fee_account=account,
            amount=Decimal('1000.00'),
            reason="Scholarship"
        )
        account.refresh_from_db()
        self.assertEqual(account.effective_fee_amount, Decimal('11000.00'))

        payment2 = FeeCollectionService.record_payment(
            fee_account=account,
            amount=Decimal('7000.00'),
            payment_method='BANK_TRANSFER',
            reference_number='NEFT-99100'
        )
        account.refresh_from_db()
        self.assertEqual(account.status, StudentFeeAccountStatus.PAID)

        summary = FeeCollectionAnalyticsSelector.get_course_fee_summary(self.course)
        self.assertEqual(summary['total_collected'], 11000.0)
        self.assertEqual(summary['outstanding_balance'], 0.0)
        self.assertEqual(summary['paid_count'], 1)
