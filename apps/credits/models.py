from decimal import Decimal

from core.models import BaseModel
from django.db import models
from django.utils import timezone

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
    DAILY_USAGE = 'DAILY_USAGE', 'Daily Recurring Usage'
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
    CERTIFICATE_ISSUE = 'CERTIFICATE_ISSUE', 'Certificate Issuance'
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
    PER_DAY = 'PER_DAY', 'Per Day (Daily Recurring)'

class SubscriptionStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended (Past Due)'
    CANCELLED = 'CANCELLED', 'Cancelled'

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
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    credits = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    currency = models.CharField(max_length=10, default='INR')
    is_purchasable = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'credit_rates'
        ordering = ['feature_key']

    def save(self, *args, **kwargs):
        from core.utils import normalize_currency
        self.currency = normalize_currency(self.currency)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"CreditRate [{self.feature_key}]: {self.credits} Credits for {self.price} {self.currency}"

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

    def save(self, *args, **kwargs):
        from core.utils import normalize_currency
        self.currency = normalize_currency(self.currency)
        super().save(*args, **kwargs)

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
    rate = models.ForeignKey(
        'credits.CreditRate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases'
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

    def save(self, *args, **kwargs):
        from core.utils import normalize_currency
        self.currency = normalize_currency(self.currency)
        super().save(*args, **kwargs)

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

# --------------------------------------------------------------
# Credit Usage Subscription (Daily Recurring Usage)
# --------------------------------------------------------------

class CreditUsageSubscription(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='credit_subscriptions'
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='credit_subscriptions'
    )
    resource_type = models.CharField(max_length=100, db_index=True) # e.g. 'COURSE_FEATURE', 'STORAGE_MEDIA'
    resource_id = models.CharField(max_length=255, db_index=True)   # e.g. 'LIVE_CLASS' or media file UUID
    billing_type = models.CharField(
        max_length=20,
        choices=BillingType.choices,
        default=BillingType.PER_DAY
    )
    daily_credit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0.0000'))
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True
    )
    started_at = models.DateTimeField(default=timezone.now)
    stopped_at = models.DateTimeField(null=True, blank=True)
    last_charged_date = models.DateField(null=True, blank=True, db_index=True)
    next_charge_date = models.DateField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'credit_usage_subscriptions'
        unique_together = ('academy', 'resource_type', 'resource_id')
        ordering = ['-created_at']

    def __str__(self):
        return f"CreditUsageSubscription [{self.academy_id} - {self.resource_type}:{self.resource_id}]: {self.daily_credit_cost} Credits/day ({self.status})"

# --------------------------------------------------------------
# Feature Billing Rule (Section A)
# Super Admin Configured Feature Rules
# --------------------------------------------------------------

class FeatureBillingType(models.TextChoices):
    INCLUDED = 'INCLUDED', 'Included (0 Credits)'
    PER_STUDENT = 'PER_STUDENT', 'Per Student Enrolled'
    PER_USAGE = 'PER_USAGE', 'Per Usage Event'
    PER_DAY = 'PER_DAY', 'Per Day (Daily Recurring)'
    FIXED_MONTHLY = 'FIXED_MONTHLY', 'Fixed Monthly Charge'

class FeatureBillingRule(BaseModel):
    feature_code = models.CharField(max_length=100, db_index=True)
    billing_type = models.CharField(
        max_length=20,
        choices=FeatureBillingType.choices,
        default=FeatureBillingType.INCLUDED
    )
    credit_rate = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0.0000'))
    is_billable = models.BooleanField(default=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    effective_from = models.DateTimeField(default=timezone.now, db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'credit_feature_billing_rules'
        ordering = ['feature_code', '-effective_from']

    def __str__(self):
        return f"FeatureBillingRule [{self.feature_code}]: {self.billing_type} @ {self.credit_rate} Credits"

# --------------------------------------------------------------
# Storage Billing Setting (Section E)
# Super Admin Configured Metered Storage Rules
# --------------------------------------------------------------

class StorageBillingMethod(models.TextChoices):
    AVERAGE_DAILY = 'AVERAGE_DAILY', 'Average Daily Usage'

class StorageBillingSetting(BaseModel):
    enabled = models.BooleanField(default=True, db_index=True)
    free_bytes = models.BigIntegerField(default=5368709120)  # Default 5 GB in bytes (5 * 1024^3)
    credits_per_gb = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('5.0000'))
    billing_method = models.CharField(
        max_length=30,
        choices=StorageBillingMethod.choices,
        default=StorageBillingMethod.AVERAGE_DAILY
    )
    effective_from = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'credit_storage_billing_settings'
        ordering = ['-effective_from']

    def __str__(self):
        return f"StorageBillingSetting: {'ON' if self.enabled else 'OFF'} - {self.credits_per_gb} Credits/GB/month"

# --------------------------------------------------------------
# Academy Storage Usage & Snapshot (Section E)
# --------------------------------------------------------------

class AcademyStorageUsage(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='credit_storage_usage'
    )
    used_bytes = models.BigIntegerField(default=0)

    class Meta:
        db_table = 'credit_academy_storage_usages'

    def __str__(self):
        return f"AcademyStorageUsage [{self.academy_id}]: {self.used_bytes} bytes"

class AcademyStorageDailySnapshot(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='storage_daily_snapshots'
    )
    date = models.DateField(db_index=True)
    used_bytes = models.BigIntegerField(default=0)

    class Meta:
        db_table = 'credit_academy_storage_snapshots'
        unique_together = ('academy', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"StorageSnapshot [{self.academy_id} - {self.date}]: {self.used_bytes} bytes"

# --------------------------------------------------------------
# Monthly Billing Engine Models (Section H)
# --------------------------------------------------------------

class MonthlyBillingPeriodStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    CLOSED = 'CLOSED', 'Closed'
    FINALIZED = 'FINALIZED', 'Finalized'

class MonthlyBillingPeriod(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='billing_periods'
    )
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=MonthlyBillingPeriodStatus.choices,
        default=MonthlyBillingPeriodStatus.OPEN,
        db_index=True
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'credit_monthly_billing_periods'
        unique_together = ('academy', 'period_start', 'period_end')
        ordering = ['-period_start']

    def __str__(self):
        return f"BillingPeriod [{self.academy_id}]: {self.period_start.strftime('%Y-%m')} ({self.status})"

class InvoiceStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    FINALIZED = 'FINALIZED', 'Finalized & Charged'
    INSUFFICIENT_CREDITS = 'INSUFFICIENT_CREDITS', 'Insufficient Credits'

class MonthlyBillingInvoice(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='monthly_invoices'
    )
    billing_period = models.ForeignKey(
        MonthlyBillingPeriod,
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    total_credits = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    status = models.CharField(
        max_length=30,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.FINALIZED,
        db_index=True
    )
    generated_at = models.DateTimeField(default=timezone.now)
    finalized_at = models.DateTimeField(null=True, blank=True)
    ledger_entry = models.ForeignKey(
        CreditLedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='monthly_invoices'
    )

    class Meta:
        db_table = 'credit_monthly_billing_invoices'
        ordering = ['-generated_at']

    def __str__(self):
        return f"Invoice [{self.academy_id} - {self.id}]: {self.total_credits} Credits ({self.status})"

class LineItemType(models.TextChoices):
    STUDENT_BASE = 'STUDENT_BASE', 'Student Base Access'
    LIVE_CLASS = 'LIVE_CLASS', 'Live Class Feature'
    ONE_TO_ONE = 'ONE_TO_ONE', 'One-to-One Session Feature'
    CERTIFICATE = 'CERTIFICATE', 'Certificate Issuance'
    ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement Post'
    EMAIL = 'EMAIL', 'Email Delivery'
    STORAGE = 'STORAGE', 'Storage Monthly Usage'
    FIXED_MONTHLY = 'FIXED_MONTHLY', 'Fixed Monthly Charge'
    OTHER = 'OTHER', 'Other Feature Usage'

class MonthlyBillingLineItem(BaseModel):
    invoice = models.ForeignKey(
        MonthlyBillingInvoice,
        on_delete=models.CASCADE,
        related_name='line_items'
    )
    item_type = models.CharField(
        max_length=30,
        choices=LineItemType.choices,
        default=LineItemType.OTHER,
        db_index=True
    )
    feature_code = models.CharField(max_length=100, blank=True, default='')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal('0.0000'))
    unit = models.CharField(max_length=30, default='units')  # e.g., 'students', 'events', 'GB'
    rate = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('0.0000'))
    credits = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'credit_monthly_billing_line_items'
        ordering = ['id']

    def __str__(self):
        return f"LineItem [{self.item_type}]: {self.quantity} {self.unit} @ {self.rate} = {self.credits} Credits"

# --------------------------------------------------------------
# Feature Usage Event (Section K)
# Trusted backend usage events for PER_USAGE features
# --------------------------------------------------------------

class FeatureUsageEvent(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='feature_usage_events'
    )
    feature_code = models.CharField(max_length=100, db_index=True)
    quantity = models.IntegerField(default=1)
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, default='')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    billed = models.BooleanField(default=False, db_index=True)
    billing_period = models.ForeignKey(
        MonthlyBillingPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usage_events'
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'credit_feature_usage_events'
        ordering = ['-occurred_at']

class CourseFeatureBilledStudent(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='feature_billed_students'
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='feature_billed_students'
    )
    student = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='feature_billed_entitlements'
    )
    feature_code = models.CharField(max_length=100, db_index=True)
    ledger_entry = models.ForeignKey(
        'credits.CreditLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billed_student_entitlements'
    )
    billed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'credit_course_feature_billed_students'
        unique_together = ('course', 'student', 'feature_code')
        ordering = ['-billed_at']

    def __str__(self):
        return f"BilledStudent [{self.feature_code}] - Course {self.course_id}, Student {self.student_id}"



