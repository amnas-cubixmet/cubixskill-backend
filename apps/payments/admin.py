from django.contrib import admin
from payments.models import (
    Coupon,
    CouponRedemption,
    PaymentInvoice,
    PaymentOrder,
    PaymentRefund,
    PaymentTransaction,
    PaymentWebhookEvent,
)

# --------------------------------------------------------------
# 1. Coupon Admin
# --------------------------------------------------------------

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'scope', 'academy', 'discount_type', 'discount_value', 'is_active', 'valid_from', 'valid_until']
    list_filter = ['scope', 'discount_type', 'is_active']
    search_fields = ['code', 'name', 'academy__name']

# --------------------------------------------------------------
# 2. Payment Order Admin
# --------------------------------------------------------------

@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'payment_context', 'academy', 'payer', 'final_amount', 'currency', 'status', 'gateway', 'completed_at']
    list_filter = ['payment_context', 'status', 'gateway', 'currency']
    search_fields = ['order_number', 'payer__email', 'academy__name', 'gateway_order_id']
    readonly_fields = ['order_number', 'completed_at']

# --------------------------------------------------------------
# 3. Payment Transaction Admin
# --------------------------------------------------------------

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'gateway', 'payment_method', 'amount', 'currency', 'status', 'paid_at']
    list_filter = ['gateway', 'status', 'payment_method']
    search_fields = ['gateway_payment_id', 'order__order_number']

# --------------------------------------------------------------
# 4. Coupon Redemption Admin
# --------------------------------------------------------------

@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ['coupon', 'order', 'user', 'discount_amount', 'redeemed_at']
    search_fields = ['coupon__code', 'user__email', 'order__order_number']

# --------------------------------------------------------------
# 5. Payment Refund Admin
# --------------------------------------------------------------

@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = ['refund_number', 'order', 'amount', 'status', 'requested_at', 'processed_at']
    list_filter = ['status']
    search_fields = ['refund_number', 'order__order_number']

# --------------------------------------------------------------
# 6. Payment Invoice Admin
# --------------------------------------------------------------

@admin.register(PaymentInvoice)
class PaymentInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'order', 'buyer_name_snapshot', 'total_amount', 'currency', 'status', 'issued_at']
    search_fields = ['invoice_number', 'order__order_number', 'buyer_name_snapshot']

# --------------------------------------------------------------
# 7. Payment Webhook Event Admin
# --------------------------------------------------------------

@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'gateway', 'event_type', 'signature_valid', 'processed', 'received_at']
    list_filter = ['gateway', 'processed', 'signature_valid']
    search_fields = ['event_id', 'event_type']
