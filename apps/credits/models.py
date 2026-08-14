from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import BaseModel

# --------------------------------------------------------------
# Credit Enums & Constants
# --------------------------------------------------------------

class CreditAccountStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    CLOSED = 'CLOSED', 'Closed'

class LedgerEntryType(models.TextChoices):
    CREDIT = 'CREDIT', 'Credit (+)'
    DEBIT = 'DEBIT', 'Debit (-)'

class CreditSourceType(models.TextChoices):
    PURCHASE = 'PURCHASE', 'Credit Package Purchase'
    STORAGE_USAGE = 'STORAGE_USAGE', 'Storage Usage Billing'
    PLAN_GRANT = 'PLAN_GRANT', 'Plan Subscription Grant'
    ADD_ON_GRANT = 'ADD_ON_GRANT', 'Add-On Grant'
    PROMOTIONAL = 'PROMOTIONAL', 'Promotional Grant'
    MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Super Admin Manual Adjustment'
    REFUND = 'REFUND', 'Purchase Refund Adjustment'
    REVERSAL = 'REVERSAL', 'Ledger Entry Reversal'
    EXPIRY = 'EXPIRY', 'Credit Expiry'
    AI_USAGE = 'AI_USAGE', 'AI Metered Service Usage'
    SMS_USAGE = 'SMS_USAGE', 'SMS Communication Usage'
    OTHER = 'OTHER', 'Other Platform Service'

class AdjustmentType(models.TextChoices):
    ADD = 'ADD', 'Add Credits (+)'
    DEDUCT = 'DEDUCT', 'Deduct Credits (-)'

class AdjustmentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Approval'
    APPROVED = 'APPROVED', 'Approved & Applied'
    REJECTED = 'REJECTED', 'Rejected'
    CANCELLED = 'CANCELLED', 'Cancelled'

# --------------------------------------------------------------
# Credit Account
# Belongs to Academy (not individual staff).
# CreditAccount.balance is only the cached current balance.
# All balance updates must go through CreditsService.
# --------------------------------------------------------------

class CreditAccount(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='credit_account'
    )
    currency_unit = models.CharField(max_length=20, default='CREDITS')
    balance = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))

    total_credited = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    total_debited = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))

    status = models.CharField(
        max_length=20,
        choices=CreditAccountStatus.choices,
        default=CreditAccountStatus.ACTIVE,
        db_index=True
    )
    last_transaction_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'credit_accounts'

    def __str__(self):
        return f"Academy {self.academy_id} Balance: {self.balance} {self.currency_unit}"

# --------------------------------------------------------------
# Credit Ledger Entry
# Immutable and append-only financial source of truth.
# Balance update + ledger entry must happen atomically.
# Use Decimal, never float, for credit values.
# Idempotency prevents duplicate debits/credits.
# Negative balance allowed only for trusted post-usage billing.
# Storage calculates usage; Credits owns the financial debit.
# Refunds/reversals create new ledger entries, never edit old ones.
# --------------------------------------------------------------

class CreditLedgerEntry(BaseModel):
    account = models.ForeignKey(
        CreditAccount,
        on_delete=models.CASCADE,
        related_name='ledger_entries'
    )

    entry_type = models.CharField(
        max_length=10,
        choices=LedgerEntryType.choices,
        db_index=True
    )
    source_type = models.CharField(
        max_length=50,
        choices=CreditSourceType.choices,
        default=CreditSourceType.PURCHASE,
        db_index=True
    )

    amount = models.DecimalField(max_digits=20, decimal_places=6)

    balance_before = models.DecimalField(max_digits=20, decimal_places=6)
    balance_after = models.DecimalField(max_digits=20, decimal_places=6)

    reference_type = models.CharField(max_length=50, blank=True, default='')
    reference_id = models.CharField(max_length=255, blank=True, default='')

    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)

    description = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'credit_ledger_entries'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['account', 'entry_type']),
            models.Index(fields=['account', 'source_type']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f"LedgerEntry [{self.entry_type}] {self.amount} ({self.source_type}) - Key: {self.idempotency_key}"

# --------------------------------------------------------------
# Credit Adjustment
# Manual adjustments must have a reason and be audited.
# Corrections create new compensating ledger entries.
# --------------------------------------------------------------

class CreditAdjustment(BaseModel):
    account = models.ForeignKey(
        CreditAccount,
        on_delete=models.CASCADE,
        related_name='adjustments'
    )
    adjustment_type = models.CharField(
        max_length=10,
        choices=AdjustmentType.choices,
        default=AdjustmentType.ADD
    )
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=AdjustmentStatus.choices,
        default=AdjustmentStatus.APPROVED,
        db_index=True
    )

    ledger_entry = models.ForeignKey(
        CreditLedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    requested_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    approved_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'credit_adjustments'
        ordering = ['-created_at']

    def __str__(self):
        return f"CreditAdjustment [{self.adjustment_type}] {self.amount} for Account {self.account_id}"
