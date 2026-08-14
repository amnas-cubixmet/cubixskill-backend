import uuid
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditAdjustment,
    CreditAccountStatus,
    LedgerEntryType,
    CreditSourceType,
    AdjustmentType,
    AdjustmentStatus,
)

# --------------------------------------------------------------
# Credits Service
# Central service for credit and debit mutations.
# All balance updates and ledger entries must commit atomically.
# Idempotency key prevents duplicate transactions.
# Payments can add credits only after backend-verified payment success.
# Storage calculates usage; Credits owns the financial debit.
# --------------------------------------------------------------

class CreditsService:

    @classmethod
    def get_or_create_account(cls, academy: Academy) -> CreditAccount:
        account, _ = CreditAccount.objects.get_or_create(academy=academy)
        return account

    @classmethod
    def get_balance(cls, academy: Academy) -> Decimal:
        account = cls.get_or_create_account(academy)
        return account.balance

    @classmethod
    @transaction.atomic
    def credit(
        cls,
        academy: Academy,
        amount: Decimal,
        source_type: str,
        idempotency_key: str,
        description: str = "",
        reference_type: str = "",
        reference_id: str = "",
        created_by: User = None,
        metadata: dict = None
    ) -> CreditLedgerEntry:
        """
        Increases Academy credit balance atomically and appends an immutable ledger entry.
        Idempotent operation using database-level uniqueness constraint.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Credit amount must be positive."})

        # Idempotency check
        existing = CreditLedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        account = CreditAccount.objects.select_for_update().get(id=cls.get_or_create_account(academy).id)
        balance_before = account.balance
        balance_after = balance_before + amount

        now = timezone.now()
        account.balance = balance_after
        account.total_credited += amount
        account.last_transaction_at = now
        account.save(update_fields=['balance', 'total_credited', 'last_transaction_at'])

        entry = CreditLedgerEntry.objects.create(
            account=account,
            entry_type=LedgerEntryType.CREDIT,
            source_type=source_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id),
            idempotency_key=idempotency_key,
            description=description or f"Credited {amount} ({source_type})",
            metadata=metadata or {},
            created_by=created_by,
            occurred_at=now
        )

        return entry

    @classmethod
    @transaction.atomic
    def debit(
        cls,
        academy: Academy,
        amount: Decimal,
        source_type: str,
        idempotency_key: str,
        description: str = "",
        reference_type: str = "",
        reference_id: str = "",
        created_by: User = None,
        metadata: dict = None,
        allow_negative: bool = False
    ) -> CreditLedgerEntry:
        """
        Decreases Academy credit balance atomically and appends an immutable ledger entry.
        For trusted post-usage metered services (e.g. storage billing), allow_negative=True is supported.
        Normal client requests must never pass allow_negative=True.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Debit amount must be positive."})

        # Idempotency check
        existing = CreditLedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        account = CreditAccount.objects.select_for_update().get(id=cls.get_or_create_account(academy).id)

        if account.status == CreditAccountStatus.SUSPENDED and not allow_negative:
            raise ValidationError({"account": "Credit account is suspended."})

        balance_before = account.balance

        if not allow_negative and balance_before < amount:
            raise ValidationError({"balance": "Insufficient credit balance for this operation."})

        balance_after = balance_before - amount
        now = timezone.now()

        account.balance = balance_after
        account.total_debited += amount
        account.last_transaction_at = now
        account.save(update_fields=['balance', 'total_debited', 'last_transaction_at'])

        entry = CreditLedgerEntry.objects.create(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            source_type=source_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id),
            idempotency_key=idempotency_key,
            description=description or f"Debited {amount} ({source_type})",
            metadata=metadata or {},
            created_by=created_by,
            occurred_at=now
        )

        return entry

    @classmethod
    @transaction.atomic
    def adjust(
        cls,
        academy: Academy,
        amount: Decimal,
        adjustment_type: str,
        reason: str,
        requested_by: User = None,
        approved_by: User = None
    ) -> CreditAdjustment:
        """
        Executes Super Admin manual credit addition or deduction with audit record.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Adjustment amount must be positive."})

        account = cls.get_or_create_account(academy)
        idempotency_key = f"adjustment:{uuid.uuid4().hex}"

        adjustment = CreditAdjustment.objects.create(
            account=account,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            status=AdjustmentStatus.APPROVED,
            requested_by=requested_by,
            approved_by=approved_by or requested_by
        )

        if adjustment_type == AdjustmentType.ADD:
            entry = cls.credit(
                academy=academy,
                amount=amount,
                source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                idempotency_key=idempotency_key,
                description=f"Manual credit addition: {reason}",
                reference_type="CREDIT_ADJUSTMENT",
                reference_id=str(adjustment.id),
                created_by=requested_by
            )
        elif adjustment_type == AdjustmentType.DEDUCT:
            entry = cls.debit(
                academy=academy,
                amount=amount,
                source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                idempotency_key=idempotency_key,
                description=f"Manual credit deduction: {reason}",
                reference_type="CREDIT_ADJUSTMENT",
                reference_id=str(adjustment.id),
                created_by=requested_by,
                allow_negative=True
            )
        else:
            raise ValidationError({"adjustment_type": "Invalid adjustment type."})

        adjustment.ledger_entry = entry
        adjustment.save(update_fields=['ledger_entry'])

        return adjustment

    @classmethod
    @transaction.atomic
    def reverse_entry(cls, entry_id: str, reason: str, performed_by: User = None) -> CreditLedgerEntry:
        """
        Reverses a finalized ledger entry via a compensating entry. Never edits history.
        """
        try:
            target_entry = CreditLedgerEntry.objects.get(id=entry_id)
        except CreditLedgerEntry.DoesNotExist:
            raise ValidationError({"entry_id": "Ledger entry not found."})

        reversal_key = f"reversal:{target_entry.id}"
        academy = target_entry.account.academy

        if target_entry.entry_type == LedgerEntryType.CREDIT:
            compensating_entry = cls.debit(
                academy=academy,
                amount=target_entry.amount,
                source_type=CreditSourceType.REVERSAL,
                idempotency_key=reversal_key,
                description=f"Reversal of Credit entry {target_entry.id}: {reason}",
                reference_type="CREDIT_LEDGER_ENTRY",
                reference_id=str(target_entry.id),
                created_by=performed_by,
                allow_negative=True
            )
        else:
            compensating_entry = cls.credit(
                academy=academy,
                amount=target_entry.amount,
                source_type=CreditSourceType.REVERSAL,
                idempotency_key=reversal_key,
                description=f"Reversal of Debit entry {target_entry.id}: {reason}",
                reference_type="CREDIT_LEDGER_ENTRY",
                reference_id=str(target_entry.id),
                created_by=performed_by
            )

        return compensating_entry

    @classmethod
    def reconcile_account(cls, academy: Academy) -> tuple[bool, Decimal, Decimal]:
        """
        Reconciles sum(CREDIT) - sum(DEBIT) against cached CreditAccount.balance.
        Returns: (is_valid, expected_balance, actual_balance)
        """
        account = cls.get_or_create_account(academy)

        credits_sum = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.CREDIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        debits_sum = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        expected_balance = (credits_sum - debits_sum).quantize(Decimal('0.000001'))
        actual_balance = account.balance.quantize(Decimal('0.000001'))

        is_valid = (expected_balance == actual_balance)
        return is_valid, expected_balance, actual_balance
