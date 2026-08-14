from rest_framework import serializers
from payments.models import (
    Coupon,
    PaymentOrder,
    PaymentTransaction,
    PaymentRefund,
    PaymentInvoice,
    PaymentContext,
    GatewayType,
    PaymentMethod,
)

# --------------------------------------------------------------
# 1. Coupon Serializers
# --------------------------------------------------------------

class CouponSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)
    courses_ids = serializers.PrimaryKeyRelatedField(source='courses', many=True, read_only=True)

    class Meta:
        model = Coupon
        fields = [
            'id',
            'code',
            'name',
            'description',
            'scope',
            'academy_id',
            'discount_type',
            'discount_value',
            'max_discount_amount',
            'minimum_order_amount',
            'valid_from',
            'valid_until',
            'total_usage_limit',
            'per_user_usage_limit',
            'current_usage_count',
            'first_purchase_only',
            'is_active',
            'courses_ids',
            'created_at',
        ]
        read_only_fields = ['id', 'current_usage_count', 'created_at']

class CreateCouponSerializer(serializers.ModelSerializer):
    course_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )

    class Meta:
        model = Coupon
        fields = [
            'code',
            'name',
            'description',
            'discount_type',
            'discount_value',
            'max_discount_amount',
            'minimum_order_amount',
            'valid_from',
            'valid_until',
            'total_usage_limit',
            'per_user_usage_limit',
            'first_purchase_only',
            'course_ids',
        ]

class ValidateCouponSerializer(serializers.Serializer):
    coupon_code = serializers.CharField(max_length=50)
    payment_context = serializers.ChoiceField(choices=PaymentContext.choices, default=PaymentContext.COURSE_PURCHASE)
    course_id = serializers.UUIDField(required=False, allow_null=True)

class CourseCheckoutSerializer(serializers.Serializer):
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')
    gateway = serializers.ChoiceField(choices=GatewayType.choices, default=GatewayType.RAZORPAY)

class PlatformCheckoutSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(required=False, allow_null=True)
    add_on_id = serializers.UUIDField(required=False, allow_null=True)
    credits_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')
    gateway = serializers.ChoiceField(choices=GatewayType.choices, default=GatewayType.RAZORPAY)

    def validate(self, attrs):
        if not attrs.get('plan_id') and not attrs.get('add_on_id') and not attrs.get('credits_amount'):
            raise serializers.ValidationError("Must specify plan_id, add_on_id, or credits_amount.")
        return attrs

class PayOrderSerializer(serializers.Serializer):
    gateway_payment_id = serializers.CharField(max_length=255)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.OTHER)
    gateway_signature = serializers.CharField(required=False, allow_blank=True, default='')

class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            'id',
            'gateway',
            'payment_method',
            'gateway_payment_id',
            'amount',
            'currency',
            'status',
            'paid_at',
            'initiated_at',
        ]

class PaymentRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = [
            'id',
            'refund_number',
            'amount',
            'reason',
            'status',
            'requested_at',
            'processed_at',
        ]

class PaymentInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentInvoice
        fields = [
            'id',
            'invoice_number',
            'seller_name_snapshot',
            'buyer_name_snapshot',
            'subtotal_amount',
            'discount_amount',
            'tax_amount',
            'total_amount',
            'currency',
            'issued_at',
            'status',
        ]

class PaymentOrderSerializer(serializers.ModelSerializer):
    payer_email = serializers.EmailField(source='payer.email', read_only=True)
    academy_name = serializers.CharField(source='academy.name', read_only=True)
    invoice = PaymentInvoiceSerializer(read_only=True)
    transactions = PaymentTransactionSerializer(many=True, read_only=True)
    refunds = PaymentRefundSerializer(many=True, read_only=True)
    coupon_code = serializers.CharField(source='coupon.code', read_only=True)

    class Meta:
        model = PaymentOrder
        fields = [
            'id',
            'order_number',
            'payment_context',
            'academy_name',
            'payer_email',
            'course_title_snapshot',
            'product_name_snapshot',
            'subtotal_amount',
            'discount_amount',
            'tax_amount',
            'final_amount',
            'currency',
            'coupon_code',
            'status',
            'gateway',
            'gateway_order_id',
            'invoice',
            'transactions',
            'refunds',
            'completed_at',
            'created_at',
        ]
        read_only_fields = fields
