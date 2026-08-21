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
    EMAIL_USAGE = 'EMAIL_USAGE', 'Email Communication Usage'
    PLAN_GRANT = 'PLAN_GRANT', 'Plan Subscription Grant'
    ADD_ON_GRANT = 'ADD_ON_GRANT', 'Add-On Grant'
    PROMOTIONAL = 'PROMOTIONAL', 'Promotional Grant'
    MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Super Admin Manual Adjustment'
    REFUND = 'REFUND', 'Purchase Refund Adjustment'
    REVERSAL = 'REVERSAL', 'Ledger Entry Reversal'
    EXPIRY = 'EXPIRY', 'Credit Expiry'
    AI_USAGE = 'AI_USAGE', 'AI Metered Service Usage'
    SMS_USAGE = 'SMS_USAGE', 'SMS Communication Usage'
    COUPON_BONUS = 'COUPON_BONUS', 'Coupon Bonus Credits'
    OTHER = 'OTHER', 'Other Platform Service'

class AdjustmentType(models.TextChoices):
    ADD = 'ADD', 'Add Credits (+)'
    DEDUCT = 'DEDUCT', 'Deduct Credits (-)'

class AdjustmentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Approval'
    APPROVED = 'APPROVED', 'Approved & Applied'
    REJECTED = 'REJECTED', 'Rejected'
    CANCELLED = 'CANCELLED', 'Cancelled'

class BillingType(models.TextChoices):
    PER_UNIT = 'PER_UNIT', 'Per Unit'
    PER_BLOCK = 'PER_BLOCK', 'Per Block'
    FIXED = 'FIXED', 'Fixed Rate'

class CouponDiscountType(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'Percentage Discount'
    FIXED_AMOUNT = 'FIXED_AMOUNT', 'Fixed Currency Amount'
    BONUS_CREDITS = 'BONUS_CREDITS', 'Bonus Credits'

class PurchaseStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Payment'
    PAID = 'PAID', 'Paid (Awaiting Fulfillment)'
    FULFILLED = 'FULFILLED', 'Fulfilled & Credited'
    FAILED = 'FAILED', 'Payment Failed'
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
# Credit Rate Configuration (Super Admin Configurable)
# --------------------------------------------------------------

class CreditRate(BaseModel):
    feature_key = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    billing_type = models.CharField(
        max_length=20,
        choices=BillingType.choices,
        default=BillingType.PER_UNIT
    )
    unit_size = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('1.0000'))
    credit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('1.0000'))
    is_active = models.BooleanField(default=True, db_index=True)
    effective_from = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'credit_rates'
        ordering = ['feature_key']

    def __str__(self):
        return f"CreditRate [{self.feature_key}]: {self.credit_cost} Credits per {self.unit_size} units"

# --------------------------------------------------------------
# Credit Package (For Purchase)
# --------------------------------------------------------------

class CreditPackage(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    credits = models.DecimalField(max_digits=20, decimal_places=6)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    bonus_credits = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'credit_packages'
        ordering = ['sort_order', 'price']

    def __str__(self):
        return f"CreditPackage [{self.name}]: {self.credits} Credits for {self.price} {self.currency}"

# --------------------------------------------------------------
# Credit Purchase Coupon
# --------------------------------------------------------------

class CreditPurchaseCoupon(BaseModel):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, default='')
    discount_type = models.CharField(
        max_length=20,
        choices=CouponDiscountType.choices,
        default=CouponDiscountType.PERCENTAGE
    )
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)
    min_purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    max_discount_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    usage_limit = models.IntegerField(null=True, blank=True)
    current_usage_count = models.IntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'credit_purchase_coupons'

    def __str__(self):
        return f"CreditCoupon [{self.code}]: {self.discount_value} ({self.discount_type})"

# --------------------------------------------------------------
# Credit Purchase Order Record
# --------------------------------------------------------------

class CreditPurchase(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='credit_purchases'
    )
    package = models.ForeignKey(
        CreditPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases'
    )
    coupon = models.ForeignKey(
        CreditPurchaseCoupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases'
    )
    base_credits = models.DecimalField(max_digits=20, decimal_places=6)
    bonus_credits = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    total_credits = models.DecimalField(max_digits=20, decimal_places=6)
    original_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    final_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    payment_order_id = models.CharField(max_length=255, unique=True, db_index=True)
    payment_transaction_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=PurchaseStatus.choices,
        default=PurchaseStatus.PENDING,
        db_index=True
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    ledger_entry = models.ForeignKey(
        CreditLedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        db_table = 'credit_purchases'
        ordering = ['-created_at']

    def __str__(self):
        return f"CreditPurchase [{self.payment_order_id}]: {self.total_credits} Credits ({self.status})"

# --------------------------------------------------------------
# Storage Credit Charge Record
# --------------------------------------------------------------

class StorageCreditCharge(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='storage_credit_charges'
    )
    billing_period = models.CharField(max_length=20, db_index=True) # e.g. '2026-08'
    usage_bytes = models.BigIntegerField(default=0)
    billable_units_gb = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0.0000'))
    credit_rate = models.DecimalField(max_digits=12, decimal_places=4)
    credits_charged = models.DecimalField(max_digits=20, decimal_places=6)
    ledger_entry = models.ForeignKey(
        CreditLedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    status = models.CharField(max_length=20, default='CHARGED', db_index=True)

    class Meta:
        db_table = 'storage_credit_charges'
        unique_together = ('academy', 'billing_period')
        ordering = ['-created_at']

    def __str__(self):
        return f"StorageCharge [{self.academy_id} - {self.billing_period}]: {self.credits_charged} Credits"

# --------------------------------------------------------------
# Credit Adjustment
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
