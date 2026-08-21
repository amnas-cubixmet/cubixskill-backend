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
