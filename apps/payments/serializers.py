from django.utils import timezone
from payments.encryption_service import decrypt_secret, encrypt_secret
from payments.models import (
    AcademyPaymentSettings,
    AcademySettlement,
    Coupon,
    CouponRedemption,
    GatewayType,
    PaymentContext,
    PaymentInvoice,
    PaymentMethod,
    PaymentOrder,
    PaymentRefund,
    PaymentTransaction,
)
from rest_framework import serializers

# --------------------------------------------------------------
# 0. Academy Payment Settings & Settlement Serializers
# --------------------------------------------------------------

class AcademyPaymentSettingsSerializer(serializers.ModelSerializer):
    key_secret_preview = serializers.SerializerMethodField()
    webhook_secret_preview = serializers.SerializerMethodField()
    settlement_vpa_preview = serializers.SerializerMethodField()
    settlement_account_preview = serializers.SerializerMethodField()

    # Write-only fields for updating secrets safely
    razorpay_key_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    razorpay_webhook_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    settlement_vpa = serializers.CharField(write_only=True, required=False, allow_blank=True)
    settlement_account = serializers.CharField(write_only=True, required=False, allow_blank=True)
    settlement_ifsc = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = AcademyPaymentSettings
        fields = [
            'id',
            'payment_mode',
            'razorpay_key_id',
            'razorpay_environment',
            'credentials_configured',
            'credentials_verified',
            'settlement_method',
            'beneficiary_name',
            'razorpay_linked_account_id',
            'settlement_enabled',
            'kyc_status',
            'key_secret_preview',
            'webhook_secret_preview',
            'settlement_vpa_preview',
            'settlement_account_preview',
            'razorpay_key_secret',
            'razorpay_webhook_secret',
            'settlement_vpa',
            'settlement_account',
            'settlement_ifsc',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'credentials_configured', 'credentials_verified', 'created_at', 'updated_at']

    def get_key_secret_preview(self, obj):
        decrypted = decrypt_secret(obj.razorpay_key_secret_encrypted)
        if not decrypted:
            return ''
        return '••••••••••••••••'

    def get_webhook_secret_preview(self, obj):
        decrypted = decrypt_secret(obj.razorpay_webhook_secret_encrypted)
        if not decrypted:
            return ''
        return '••••••••••••••••'

    def get_settlement_vpa_preview(self, obj):
        decrypted = decrypt_secret(obj.settlement_vpa_encrypted)
        if not decrypted:
            return ''
        parts = decrypted.split('@')
        if len(parts) == 2:
            handle = parts[0]
            masked_handle = handle[:2] + '***' if len(handle) > 2 else handle + '***'
            return f"{masked_handle}@{parts[1]}"
        return '***@upi'

    def get_settlement_account_preview(self, obj):
        decrypted = decrypt_secret(obj.settlement_account_encrypted)
        if not decrypted:
            return ''
        return f"XXXX XXXX {decrypted[-4:]}" if len(decrypted) >= 4 else 'XXXX XXXX ****'

    def update(self, instance, validated_data):
        # Extract secret inputs and encrypt before storing
        key_secret = validated_data.pop('razorpay_key_secret', None)
        webhook_secret = validated_data.pop('razorpay_webhook_secret', None)
        settlement_vpa = validated_data.pop('settlement_vpa', None)
        settlement_account = validated_data.pop('settlement_account', None)
        settlement_ifsc = validated_data.pop('settlement_ifsc', None)

        if key_secret is not None and key_secret != '••••••••••••••••':
            instance.razorpay_key_secret_encrypted = encrypt_secret(key_secret)
        if webhook_secret is not None and webhook_secret != '••••••••••••••••':
            instance.razorpay_webhook_secret_encrypted = encrypt_secret(webhook_secret)
        if settlement_vpa is not None and '***' not in settlement_vpa:
            instance.settlement_vpa_encrypted = encrypt_secret(settlement_vpa)
        if settlement_account is not None and 'XXXX' not in settlement_account:
            instance.settlement_account_encrypted = encrypt_secret(settlement_account)
        if settlement_ifsc is not None:
            instance.settlement_ifsc_encrypted = encrypt_secret(settlement_ifsc)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Update configuration status flags
        has_key = bool(instance.razorpay_key_id)
        has_secret = bool(instance.razorpay_key_secret_encrypted)
        instance.credentials_configured = has_key and has_secret

        instance.save()
        return instance

class AcademySettlementSerializer(serializers.ModelSerializer):
    academy_name = serializers.CharField(source='academy.name', read_only=True)

    class Meta:
        model = AcademySettlement
        fields = [
            'id',
            'uuid',
            'academy_name',
            'period_start',
            'period_end',
            'gross_amount',
            'refund_amount',
            'gateway_fee',
            'platform_fee',
            'tax_amount',
            'net_amount',
            'settlement_method',
            'provider',
            'provider_transfer_id',
            'provider_payout_id',
            'status',
            'failure_reason',
            'initiated_at',
            'processed_at',
            'settled_at',
            'created_at',
        ]
        read_only_fields = ['id', 'uuid', 'created_at']

# --------------------------------------------------------------
# 1. Coupon Serializers
# --------------------------------------------------------------

class CouponSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)
    courses_ids = serializers.PrimaryKeyRelatedField(source='courses', many=True, read_only=True)
    computed_status = serializers.SerializerMethodField()

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
            'computed_status',
        ]
        read_only_fields = ['id', 'current_usage_count', 'created_at']

    def get_computed_status(self, obj):
        now = timezone.now()
        if not obj.is_active:
            return 'INACTIVE'
        v_from = obj.valid_from
        v_until = obj.valid_until
        if isinstance(v_from, str) and v_from.strip():
            from django.utils.dateparse import parse_date, parse_datetime
            dt = parse_datetime(v_from.strip()) or parse_date(v_from.strip())
            if dt and not isinstance(dt, timezone.datetime):
                dt = timezone.datetime.combine(dt, timezone.datetime.min.time())
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            v_from = dt
        if isinstance(v_until, str) and v_until.strip():
            from django.utils.dateparse import parse_date, parse_datetime
            dt = parse_datetime(v_until.strip()) or parse_date(v_until.strip())
            if dt and not isinstance(dt, timezone.datetime):
                dt = timezone.datetime.combine(dt, timezone.datetime.max.time())
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            v_until = dt

        if v_from and now < v_from:
            return 'SCHEDULED'
        if v_until and now > v_until:
            return 'EXPIRED'
        if obj.total_usage_limit > 0 and obj.current_usage_count >= obj.total_usage_limit:
            return 'USAGE_LIMIT_REACHED'
        return 'ACTIVE'

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
    academy_uuid = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    course_uuid = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    course_id = serializers.UUIDField(required=False, allow_null=True)

class CreateOrderApiSerializer(serializers.Serializer):
    academy_uuid = serializers.CharField(max_length=255)
    course_uuid = serializers.CharField(max_length=255)
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')
    expected_final_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)

class VerifyPaymentApiSerializer(serializers.Serializer):
    razorpay_payment_id = serializers.CharField(max_length=255)
    razorpay_order_id = serializers.CharField(max_length=255)
    razorpay_signature = serializers.CharField(max_length=512)

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
            'uuid',
            'payment_mode',
            'gateway',
            'payment_method',
            'gateway_payment_id',
            'gateway_order_id',
            'amount',
            'currency',
            'gross_amount',
            'platform_fee',
            'gateway_fee',
            'tax_amount',
            'academy_amount',
            'status',
            'signature_verified',
            'webhook_verified',
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
            'payment_mode',
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

class CouponRedemptionSerializer(serializers.ModelSerializer):
    student_id = serializers.UUIDField(source='user.id', read_only=True)
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='user.email', read_only=True)
    student_code = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    final_amount = serializers.DecimalField(source='order.final_amount', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CouponRedemption
        fields = [
            'id',
            'student_id',
            'student_name',
            'student_email',
            'student_code',
            'avatar_url',
            'order_number',
            'original_amount',
            'discount_amount',
            'final_amount',
            'redeemed_at',
            'status',
        ]

    def get_student_name(self, obj):
        if not obj.user:
            return "Anonymous User"
        return obj.user.full_name or obj.user.email.split('@')[0]

    def get_student_code(self, obj):
        if not obj.user:
            return ""
        return getattr(obj.user, 'student_code', f"STU-{str(obj.user.id)[:8]}")

    def get_avatar_url(self, obj):
        if not obj.user:
            return None
        profile = getattr(obj.user, 'profile', None) or getattr(obj.user, 'student_profile', None)
        return getattr(profile, 'profile_picture_url', None) or getattr(obj.user, 'avatar_url', None)
