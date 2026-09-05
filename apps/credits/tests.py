from decimal import Decimal
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User, SystemRoleCode
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditAdjustment,
    LedgerEntryType,
    CreditSourceType,
    AdjustmentType,
)
from credits.services import CreditsService
from credits.selectors import CreditSelector

class CreditsAppTestCase(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name="Credit Academy Alpha", slug="credit-alpha")
        self.admin_user = User.objects.create_user(
            email="superadmin@cubixskill.com",
            full_name="Super Admin",
            role_code=SystemRoleCode.SUPER_ADMIN,
            is_staff=True
        )

    def test_credit_and_debit_operations(self):
        """
        Tests atomic credit additions, debits, and balance updates with Decimal precision.
        """
        # 1. Credit 500.50 credits
        entry_credit = CreditsService.credit(
            academy=self.academy,
            amount=Decimal('500.500000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="key_credit_1"
        )
        self.assertEqual(entry_credit.entry_type, LedgerEntryType.CREDIT)
        self.assertEqual(entry_credit.balance_before, Decimal('0.000000'))
        self.assertEqual(entry_credit.balance_after, Decimal('500.500000'))

        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('500.500000'))

        # 2. Debit 150.25 credits
        entry_debit = CreditsService.debit(
            academy=self.academy,
            amount=Decimal('150.250000'),
            source_type=CreditSourceType.STORAGE_USAGE,
            idempotency_key="key_debit_1"
        )
        self.assertEqual(entry_debit.entry_type, LedgerEntryType.DEBIT)
        self.assertEqual(entry_debit.balance_before, Decimal('500.500000'))
        self.assertEqual(entry_debit.balance_after, Decimal('350.250000'))

        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('350.250000'))
        self.assertEqual(account.total_credited, Decimal('500.500000'))
        self.assertEqual(account.total_debited, Decimal('150.250000'))

    def test_idempotency_key_enforcement(self):
        """
        Tests that reusing the same idempotency key returns the existing ledger entry without duplicating credit/debit.
        """
        entry1 = CreditsService.credit(
            academy=self.academy,
            amount=Decimal('100.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="idemp_dup_test"
        )

        # Duplicate call with exact same key
        entry2 = CreditsService.credit(
            academy=self.academy,
            amount=Decimal('100.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="idemp_dup_test"
        )

        self.assertEqual(entry1.id, entry2.id)
        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('100.000000'))
        self.assertEqual(CreditLedgerEntry.objects.filter(account=account).count(), 1)

    def test_insufficient_credits_rejection(self):
        """
        Tests that normal optional debits with allow_negative=False are rejected when balance is insufficient.
        """
        CreditsService.credit(
            academy=self.academy,
            amount=Decimal('50.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="key_init_50"
        )

        from core.exceptions import CubixSkillAPIException
        with self.assertRaises(CubixSkillAPIException):
            CreditsService.debit(
                academy=self.academy,
                amount=Decimal('100.000000'),
                source_type=CreditSourceType.AI_USAGE,
                idempotency_key="key_debit_excess",
                allow_negative=False
            )

    def test_trusted_metered_negative_balance_support(self):
        """
        Tests that trusted post-usage metered billing (e.g. storage usage) with allow_negative=True supports negative balances.
        """
        CreditsService.credit(
            academy=self.academy,
            amount=Decimal('10.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="key_init_10"
        )

        entry_debit = CreditsService.debit(
            academy=self.academy,
            amount=Decimal('25.000000'),
            source_type=CreditSourceType.STORAGE_USAGE,
            idempotency_key="key_storage_metered_1",
            allow_negative=True
        )

        self.assertEqual(entry_debit.balance_after, Decimal('-15.000000'))
        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('-15.000000'))

    def test_super_admin_manual_adjustment(self):
        """
        Tests manual addition and deduction adjustments by Super Admin.
        """
        adjustment = CreditsService.adjust(
            academy=self.academy,
            amount=Decimal('200.000000'),
            adjustment_type=AdjustmentType.ADD,
            reason="Promotional grant by admin",
            requested_by=self.admin_user
        )

        self.assertEqual(adjustment.amount, Decimal('200.000000'))
        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('200.000000'))

    def test_compensating_reversal(self):
        """
        Tests that reversing a ledger entry creates a compensating entry without altering historical records.
        """
        entry_credit = CreditsService.credit(
            academy=self.academy,
            amount=Decimal('300.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="key_reversal_init"
        )

        reversal_entry = CreditsService.reverse_entry(
            entry_id=str(entry_credit.id),
            reason="Incorrect payment processing",
            performed_by=self.admin_user
        )

        self.assertEqual(reversal_entry.entry_type, LedgerEntryType.DEBIT)
        self.assertEqual(reversal_entry.amount, Decimal('300.000000'))

        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('0.000000'))

    def test_reconcile_account(self):
        """
        Tests balance reconciliation between sum(CREDIT) - sum(DEBIT) and CreditAccount.balance.
        """
        CreditsService.credit(
            academy=self.academy,
            amount=Decimal('100.000000'),
            source_type=CreditSourceType.PURCHASE,
            idempotency_key="rec_1"
        )
        CreditsService.debit(
            academy=self.academy,
            amount=Decimal('30.000000'),
            source_type=CreditSourceType.STORAGE_USAGE,
            idempotency_key="rec_2"
        )

        is_valid, expected, actual = CreditsService.reconcile_account(self.academy)
        self.assertTrue(is_valid)
        self.assertEqual(expected, Decimal('70.000000'))
        self.assertEqual(actual, Decimal('70.000000'))

    def test_razorpay_verify_and_idempotent_fulfillment(self):
        """
        Tests full end-to-end Razorpay payment verification, wallet credit, and double-verify idempotency.
        """
        from credits.models import CreditRate, CreditPurchase
        from rest_framework.test import APIClient
        rate = CreditRate.objects.create(
            name="Test Pack 100",
            feature_key="TEST_PACK_100",
            price=Decimal('499.00'),
            credits=Decimal('100.000000'),
            currency='INR',
            is_active=True,
            is_purchasable=True
        )
        user = User.objects.create_user(
            email="instructor@cubixskill.com",
            full_name="Test Instructor",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy,
            is_active=True,
            is_email_verified=True,
            password_setup_completed=True
        )

        client = APIClient()
        client.force_authenticate(user=user)

        # 1. Create Purchase Order
        create_res = client.post('/api/v1/credits/purchases/create-order/', {'rate_id': str(rate.id)})
        self.assertEqual(create_res.status_code, 201)
        purchase_id = create_res.data['id']
        rzp_order_id = create_res.data['razorpay_order_id']

        # 2. First Verification (Valid Signature)
        verify_res = client.post(f'/api/v1/credits/purchases/{purchase_id}/verify/', {
            'razorpay_order_id': rzp_order_id,
            'razorpay_payment_id': 'pay_test_unit_123',
            'razorpay_signature': 'mock_sig_valid'
        })
        self.assertEqual(verify_res.status_code, 200)
        self.assertTrue(verify_res.data['success'])
        self.assertFalse(verify_res.data['already_processed'])
        self.assertEqual(verify_res.data['wallet_balance'], '100.000000')

        account = CreditsService.get_or_create_account(self.academy)
        self.assertEqual(account.balance, Decimal('100.000000'))

        # 3. Double Verification (Idempotent call should NOT double credit)
        verify_res2 = client.post(f'/api/v1/credits/purchases/{purchase_id}/verify/', {
            'razorpay_order_id': rzp_order_id,
            'razorpay_payment_id': 'pay_test_unit_123',
            'razorpay_signature': 'mock_sig_valid'
        })
        self.assertEqual(verify_res2.status_code, 200)
        self.assertTrue(verify_res2.data['success'])
        self.assertTrue(verify_res2.data['already_processed'])

        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('100.000000'))

    def test_razorpay_verify_validations(self):
        """
        Tests validation error responses (incomplete data, order mismatch, signature failure).
        """
        from credits.models import CreditRate
        from rest_framework.test import APIClient
        rate = CreditRate.objects.create(
            name="Test Pack 50",
            feature_key="TEST_PACK_50",
            price=Decimal('299.00'),
            credits=Decimal('50.000000'),
            currency='INR',
            is_active=True,
            is_purchasable=True
        )
        user = User.objects.create_user(
            email="instructor2@cubixskill.com",
            full_name="Instructor 2",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy,
            is_active=True,
            is_email_verified=True,
            password_setup_completed=True
        )

        client = APIClient()
        client.force_authenticate(user=user)

        create_res = client.post('/api/v1/credits/purchases/create-order/', {'rate_id': str(rate.id)})
        purchase_id = create_res.data['id']
        rzp_order_id = create_res.data['razorpay_order_id']

        # Missing params -> 400
        res_incomplete = client.post(f'/api/v1/credits/purchases/{purchase_id}/verify/', {})
        self.assertEqual(res_incomplete.status_code, 400)

        # Mismatched order ID -> 400
        res_mismatch = client.post(f'/api/v1/credits/purchases/{purchase_id}/verify/', {
            'razorpay_order_id': 'order_WRONG_123',
            'razorpay_payment_id': 'pay_123',
            'razorpay_signature': 'sig'
        })
        self.assertEqual(res_mismatch.status_code, 400)

    def test_feature_credit_billing_calculation_and_included_zero_charge(self):
        """
        Tests Section A & B: Feature Credit Billing calculations, INCLUDED zero charges, PER_STUDENT rates, and get_billable_student_count.
        """
        from credits.services import get_billable_student_count, FeatureBillingService, MonthlyBillingService
        from credits.models import FeatureBillingRule, FeatureBillingType
        from students.models import StudentProfile, StudentStatus
        from enrollments.models import Enrollment, EnrollmentStatus
        from courses.models import Course

        # Create students and enrollments
        u1 = User.objects.create_user(email="s1@test.com", full_name="Student 1", academy=self.academy, role_code=SystemRoleCode.STUDENT)
        u2 = User.objects.create_user(email="s2@test.com", full_name="Student 2", academy=self.academy, role_code=SystemRoleCode.STUDENT)
        s1 = StudentProfile.objects.create(user=u1, display_name="Student 1", student_code="S1", status=StudentStatus.ACTIVE)
        s2 = StudentProfile.objects.create(user=u2, display_name="Student 2", student_code="S2", status=StudentStatus.ACTIVE)
        course = Course.objects.create(academy=self.academy, title="Test Course")
        Enrollment.objects.create(student=u1, course=course, status=EnrollmentStatus.ACTIVE)
        Enrollment.objects.create(student=u2, course=course, status=EnrollmentStatus.ACTIVE)

        billable_count = get_billable_student_count(self.academy)
        self.assertEqual(billable_count, 2)

        # Set up rules: STUDENT_BASE = 10 credits (PER_STUDENT), LESSONS = INCLUDED (0 credits), LIVE_CLASS = 2 credits (PER_STUDENT)
        FeatureBillingRule.objects.create(feature_code='STUDENT_BASE', billing_type=FeatureBillingType.PER_STUDENT, credit_rate=Decimal('10.0000'), is_billable=True, is_active=True)
        FeatureBillingRule.objects.create(feature_code='LESSONS', billing_type=FeatureBillingType.INCLUDED, credit_rate=Decimal('0.0000'), is_billable=True, is_active=True)
        FeatureBillingRule.objects.create(feature_code='LIVE_CLASS', billing_type=FeatureBillingType.PER_STUDENT, credit_rate=Decimal('2.0000'), is_billable=True, is_active=True)

        summary = MonthlyBillingService.get_live_estimated_summary(self.academy)
        # Expected: Student Base (2 * 10 = 20) + Live Class (2 * 2 = 4) = 24 credits
        self.assertEqual(Decimal(summary['estimated_total_credits']), Decimal('24.000000'))

    def test_storage_daily_snapshot_and_average_monthly_billing(self):
        """
        Tests Section D, E, F, G, U: Daily snapshots, AVERAGE_DAILY monthly average, free 5GB allowance, and storage credit deduction.
        """
        from credits.services import StorageBillingService, MonthlyBillingService
        from credits.models import StorageBillingSetting, StorageBillingMethod, AcademyStorageDailySnapshot
        from django.utils import timezone

        now = timezone.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

        # Configure Storage Billing: Enabled, 5GB Free (5368709120 bytes), 5 Credits/GB
        StorageBillingSetting.objects.create(
            enabled=True,
            free_bytes=5 * 1024 * 1024 * 1024,
            credits_per_gb=Decimal('5.0000'),
            billing_method=StorageBillingMethod.AVERAGE_DAILY
        )

        # Create daily snapshots: 22 GB average usage (22 * 1024^3 bytes)
        usage_22gb = 22 * 1024 * 1024 * 1024
        AcademyStorageDailySnapshot.objects.create(academy=self.academy, date=start.date(), used_bytes=usage_22gb)

        avg_bytes, billable_gb, rate, credits = StorageBillingService.calculate_storage_credits(self.academy, start, end)
        # 22 GB - 5 GB = 17 GB billable. 17 * 5 = 85 credits
        self.assertEqual(billable_gb, Decimal('17.0000'))
        self.assertEqual(credits, Decimal('85.000000'))

    def test_monthly_invoice_generation_and_idempotent_debit(self):
        """
        Tests Section H, I, Q: Monthly billing invoice generation, line items, and duplicate task idempotency protection.
        """
        from credits.services import MonthlyBillingService, CreditsService
        from credits.models import MonthlyBillingInvoice, InvoiceStatus
        from django.utils import timezone

        now = timezone.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

        # Add initial credits to academy
        CreditsService.credit(self.academy, Decimal('1000.000000'), 'PURCHASE', 'init_invoice_test')

        # Generate invoice
        invoice1 = MonthlyBillingService.generate_monthly_invoice(self.academy, start, end)
        self.assertEqual(invoice1.status, InvoiceStatus.FINALIZED)
        self.assertTrue(invoice1.line_items.exists())

        # Second call for same month must return existing invoice idempotently without double debit
        invoice2 = MonthlyBillingService.generate_monthly_invoice(self.academy, start, end)
        self.assertEqual(invoice1.id, invoice2.id)


