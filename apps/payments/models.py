import uuid
from decimal import Decimal

from core.models import BaseModel
from django.db import models
from django.utils import timezone

# --------------------------------------------------------------
# Payment Context & Choices
# Distinguishes Platform purchases from Academy Course purchases.
# Monetary values must use Decimal. Float must never be used for
# payment, discount, tax, refund, or credit calculations.
# --------------------------------------------------------------

class PaymentMode(models.TextChoices):
    ACADEMY_RAZORPAY = 'ACADEMY_RAZORPAY', 'Academy Razorpay (Direct)'
    CUBIXSKILL_RAZORPAY = 'CUBIXSKILL_RAZORPAY', 'CubixSkill Razorpay (Central)'

class SettlementStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    READY = 'READY', 'Ready'
    PROCESSING = 'PROCESSING', 'Processing'
    ON_HOLD = 'ON_HOLD', 'On Hold'
    PAID = 'PAID', 'Paid'
    FAILED = 'FAILED', 'Failed'
    REVERSED = 'REVERSED', 'Reversed'

class PaymentContext(models.TextChoices):
    PLATFORM_PURCHASE = 'PLATFORM_PURCHASE', 'Platform Purchase (Plan/Add-on/Credits)'
    COURSE_PURCHASE = 'COURSE_PURCHASE', 'Course Purchase'

class OrderStatus(models.TextChoices):
    CREATED = 'CREATED', 'Created'
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'
    PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED', 'Partially Refunded'
    REFUNDED = 'REFUNDED', 'Refunded'

class TransactionStatus(models.TextChoices):
    CREATED = 'CREATED', 'Created'
    PENDING = 'PENDING', 'Pending'
    AUTHORIZED = 'AUTHORIZED', 'Authorized'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'
    PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED', 'Partially Refunded'
    REFUNDED = 'REFUNDED', 'Refunded'

class CouponScope(models.TextChoices):
    PLATFORM = 'PLATFORM', 'Platform SuperAdmin Coupon'
    ACADEMY_COURSE = 'ACADEMY_COURSE', 'Academy Course Coupon'

class DiscountType(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'Percentage'
    FIXED_AMOUNT = 'FIXED_AMOUNT', 'Fixed Amount'

class GatewayType(models.TextChoices):
    RAZORPAY = 'RAZORPAY', 'Razorpay'
    STRIPE = 'STRIPE', 'Stripe'
    PAYPAL = 'PAYPAL', 'PayPal'
    MANUAL = 'MANUAL', 'Manual Payment'

class PaymentMethod(models.TextChoices):
    CARD = 'CARD', 'Credit/Debit Card'
    UPI = 'UPI', 'UPI'
    NET_BANKING = 'NET_BANKING', 'Net Banking'
    WALLET = 'WALLET', 'Digital Wallet'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    CASH = 'CASH', 'Cash'
    OTHER = 'OTHER', 'Other'

class PaymentAttemptStatus(models.TextChoices):
    CREATED = 'CREATED', 'Created'
    ORDER_CREATED = 'ORDER_CREATED', 'Order Created'
    PENDING = 'PENDING', 'Pending'
    AUTHORIZED = 'AUTHORIZED', 'Authorized'
    PAID = 'PAID', 'Paid'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'
    REFUNDED = 'REFUNDED', 'Refunded'
    PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED', 'Partially Refunded'

class RefundStatus(models.TextChoices):
    REQUESTED = 'REQUESTED', 'Requested'
    PROCESSING = 'PROCESSING', 'Processing'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'

# --------------------------------------------------------------
# 0. AcademyPaymentSettings Model
# Tenant-isolated payment mode configuration and encrypted credentials
# --------------------------------------------------------------

class AcademyPaymentSettings(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='payment_settings'
    )
    payment_mode = models.CharField(
        max_length=50,
        choices=PaymentMode.choices,
        default=PaymentMode.CUBIXSKILL_RAZORPAY,
        db_index=True
    )

    # Mode 1: Academy Own Razorpay Credentials (Encrypted at rest)
    razorpay_key_id = models.CharField(max_length=255, blank=True, default='')
    razorpay_key_secret_encrypted = models.TextField(blank=True, default='')
    razorpay_webhook_secret_encrypted = models.TextField(blank=True, default='')
    razorpay_environment = models.CharField(max_length=20, default='test')
    credentials_configured = models.BooleanField(default=False)
    credentials_verified = models.BooleanField(default=False)

    # Mode 2: Settlement Configuration (Encrypted at rest)
    settlement_method = models.CharField(max_length=50, default='UPI') # UPI | BANK_TRANSFER | ROUTE
    beneficiary_name = models.CharField(max_length=255, blank=True, default='')
    settlement_vpa_encrypted = models.TextField(blank=True, default='')
    settlement_account_encrypted = models.TextField(blank=True, default='')
    settlement_ifsc_encrypted = models.TextField(blank=True, default='')
    razorpay_linked_account_id = models.CharField(max_length=255, blank=True, default='')
    settlement_enabled = models.BooleanField(default=True)
    kyc_status = models.CharField(max_length=30, default='NOT_REQUIRED') # NOT_REQUIRED | PENDING | APPROVED | REJECTED

    class Meta:
        db_table = 'academy_payment_settings'
        ordering = ['-created_at']

    def __str__(self):
        return f"PaymentSettings for {self.academy.name} ({self.payment_mode})"

# --------------------------------------------------------------
# 1. Coupon Model
# --------------------------------------------------------------

class Coupon(BaseModel):
    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    scope = models.CharField(
        max_length=20,
        choices=CouponScope.choices,
        default=CouponScope.ACADEMY_COURSE,
        db_index=True
    )
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='coupons'
    )

    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE
    )
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)

    max_discount_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    minimum_order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)

    total_usage_limit = models.PositiveIntegerField(default=0)  # 0 = unlimited
    per_user_usage_limit = models.PositiveIntegerField(default=1)
    current_usage_count = models.PositiveIntegerField(default=0)

    first_purchase_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    courses = models.ManyToManyField(
        'courses.Course',
        blank=True,
        related_name='applicable_coupons'
    )

    class Meta:
        db_table = 'coupons'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} ({self.scope})"

# --------------------------------------------------------------
# 2. PaymentOrder Model
# --------------------------------------------------------------

class PaymentOrder(BaseModel):
    order_number = models.CharField(max_length=100, unique=True, db_index=True)

    payment_context = models.CharField(
        max_length=30,
        choices=PaymentContext.choices,
        db_index=True
    )
    payment_mode = models.CharField(
        max_length=50,
        choices=PaymentMode.choices,
        default=PaymentMode.CUBIXSKILL_RAZORPAY,
        db_index=True
    )
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='payment_orders'
    )
    payer = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='payment_orders'
    )

    course = models.ForeignKey('courses.Course', on_delete=models.SET_NULL, null=True, blank=True)
    plan = models.ForeignKey('plans_entitlements.Plan', on_delete=models.SET_NULL, null=True, blank=True)
    add_on = models.ForeignKey('plans_entitlements.AddOn', on_delete=models.SET_NULL, null=True, blank=True)

    currency = models.CharField(max_length=10, default='INR')

    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    final_amount = models.DecimalField(max_digits=12, decimal_places=2)

    course_title_snapshot = models.CharField(max_length=255, blank=True, default='')
    product_name_snapshot = models.CharField(max_length=255, blank=True, default='')
    academy_name_snapshot = models.CharField(max_length=255, blank=True, default='')

    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(
        max_length=30,
        choices=OrderStatus.choices,
        default=OrderStatus.CREATED,
        db_index=True
    )

    gateway = models.CharField(
        max_length=50,
        choices=GatewayType.choices,
        default=GatewayType.RAZORPAY
    )
    gateway_order_id = models.CharField(max_length=255, blank=True, default='', db_index=True)

    expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'payment_orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['academy', 'status']),
            models.Index(fields=['payer', 'status']),
        ]

    def __str__(self):
        return f"Order {self.order_number} ({self.status}) - {self.currency} {self.final_amount}"

# --------------------------------------------------------------
# 3. PaymentTransaction Model
# --------------------------------------------------------------

class PaymentTransaction(BaseModel):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    payer = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    payment_mode = models.CharField(
        max_length=50,
        choices=PaymentMode.choices,
        default=PaymentMode.CUBIXSKILL_RAZORPAY,
        db_index=True
    )
    gateway = models.CharField(
        max_length=50,
        choices=GatewayType.choices,
        default=GatewayType.RAZORPAY
    )
    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.OTHER
    )

    gateway_payment_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    gateway_order_id = models.CharField(max_length=255, blank=True, default='')
    gateway_signature_reference = models.CharField(max_length=512, blank=True, default='')

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')

    # Financial Ledger Breakdown
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    gateway_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    academy_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(
        max_length=30,
        choices=TransactionStatus.choices,
        default=TransactionStatus.CREATED,
        db_index=True
    )

    signature_verified = models.BooleanField(default=False)
    webhook_verified = models.BooleanField(default=False)

    failure_code = models.CharField(max_length=100, blank=True, default='')
    failure_message = models.TextField(blank=True, default='')

    initiated_at = models.DateTimeField(default=timezone.now)
    authorized_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    raw_reference = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'payment_transactions'
        ordering = ['-initiated_at']

    def __str__(self):
        return f"Transaction {self.gateway_payment_id or self.uuid} ({self.status})"

# --------------------------------------------------------------
# 4. CouponRedemption Model
# --------------------------------------------------------------

class CouponRedemption(BaseModel):
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='redemptions')
    order = models.ForeignKey(PaymentOrder, on_delete=models.CASCADE)
    user = models.ForeignKey('users_roles.User', on_delete=models.CASCADE)
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, null=True, blank=True)

    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2)
    redeemed_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default='REDEEMED')

    class Meta:
        db_table = 'coupon_redemptions'
        ordering = ['-redeemed_at']

    def __str__(self):
        return f"Redemption: {self.coupon.code} on Order {self.order.order_number}"

# --------------------------------------------------------------
# 5. PaymentRefund Model
# --------------------------------------------------------------

class PaymentRefund(BaseModel):
    refund_number = models.CharField(max_length=100, unique=True, db_index=True)
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name='refunds')
    order = models.ForeignKey(PaymentOrder, on_delete=models.CASCADE, related_name='refunds')

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=30,
        choices=RefundStatus.choices,
        default=RefundStatus.REQUESTED,
        db_index=True
    )

    gateway_refund_id = models.CharField(max_length=255, blank=True, default='')
    requested_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True)
    requested_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'payment_refunds'
        ordering = ['-requested_at']

    def __str__(self):
        return f"Refund {self.refund_number} ({self.status}) - {self.amount}"

# --------------------------------------------------------------
# 6. AcademySettlement Model
# Central settlement ledger for Mode 2 (CubixSkill Payment Account)
# --------------------------------------------------------------

class AcademySettlement(BaseModel):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='settlements'
    )

    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    gateway_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    settlement_method = models.CharField(max_length=50, default='UPI')
    provider = models.CharField(max_length=50, default='RAZORPAY')
    provider_transfer_id = models.CharField(max_length=255, blank=True, default='')
    provider_payout_id = models.CharField(max_length=255, blank=True, default='')

    status = models.CharField(
        max_length=30,
        choices=SettlementStatus.choices,
        default=SettlementStatus.PENDING,
        db_index=True
    )
    failure_reason = models.TextField(blank=True, default='')

    initiated_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'academy_settlements'
        ordering = ['-created_at']

    def __str__(self):
        return f"Settlement {self.uuid} ({self.academy.name}) - {self.net_amount} [{self.status}]"

# --------------------------------------------------------------
# 7. PaymentInvoice Model
# --------------------------------------------------------------

class PaymentInvoice(BaseModel):
    order = models.OneToOneField(PaymentOrder, on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=100, unique=True, db_index=True)

    seller_name_snapshot = models.CharField(max_length=255, blank=True, default='')
    buyer_name_snapshot = models.CharField(max_length=255, blank=True, default='')
    seller_tax_id_snapshot = models.CharField(max_length=100, blank=True, default='')
    buyer_tax_id_snapshot = models.CharField(max_length=100, blank=True, default='')
    billing_address_snapshot = models.TextField(blank=True, default='')

    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')

    issued_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default='ISSUED')
    invoice_media = models.ForeignKey('storage.MediaFile', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'payment_invoices'
        ordering = ['-issued_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} for Order {self.order.order_number}"

# --------------------------------------------------------------
# 8. PaymentWebhookEvent Model
# --------------------------------------------------------------

class PaymentWebhookEvent(BaseModel):
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    gateway = models.CharField(max_length=50)
    event_type = models.CharField(max_length=100)
    academy = models.ForeignKey('academy.Academy', on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_events')

    signature_valid = models.BooleanField(default=True)
    processed = models.BooleanField(default=False, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'payment_webhook_events'
        ordering = ['-received_at']

    def __str__(self):
        return f"Webhook [{self.gateway}] {self.event_type} ({self.event_id})"

# --------------------------------------------------------------
# 9. Student Fee Collection Domain Models (re-exported from fees app)
# --------------------------------------------------------------
