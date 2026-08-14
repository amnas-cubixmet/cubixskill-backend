from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import BaseModel

# --------------------------------------------------------------
# Payment Context & Choices
# Distinguishes Platform purchases from Academy Course purchases.
# Monetary values must use Decimal. Float must never be used for
# payment, discount, tax, refund, or credit calculations.
# --------------------------------------------------------------

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

class RefundStatus(models.TextChoices):
    REQUESTED = 'REQUESTED', 'Requested'
    PROCESSING = 'PROCESSING', 'Processing'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'

# --------------------------------------------------------------
# 1. Coupon Model
# Platform coupons are created by Super Admin for platform purchases.
# Course coupons are created by Academy Admin/Staff for course checkouts.
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
# Represents the business payment request prior to gateway execution.
# Stores immutable financial values used at checkout.
# Monetary values use Decimal, never float.
# --------------------------------------------------------------

class PaymentOrder(BaseModel):
    order_number = models.CharField(max_length=100, unique=True, db_index=True)

    payment_context = models.CharField(
        max_length=30,
        choices=PaymentContext.choices,
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
# Represents an actual gateway transaction attempt.
# Never stores sensitive card details or CVVs.
# --------------------------------------------------------------

class PaymentTransaction(BaseModel):
    order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    payer = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
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

    status = models.CharField(
        max_length=30,
        choices=TransactionStatus.choices,
        default=TransactionStatus.CREATED,
        db_index=True
    )

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
        return f"Transaction {self.gateway_payment_id or self.id} ({self.status})"

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
# Supports full and partial refunds without corrupting transaction history.
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
# 6. PaymentInvoice Model
# Stores finalized immutable snapshot data for customer billing.
# Invoice PDF generated on demand or stored via MediaFile.
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
# 7. PaymentWebhookEvent Model
# Stores signature-verified gateway webhooks for idempotent fulfillment.
# --------------------------------------------------------------

class PaymentWebhookEvent(BaseModel):
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    gateway = models.CharField(max_length=50)
    event_type = models.CharField(max_length=100)

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
