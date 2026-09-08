from credits.models import (
    AdjustmentType,
    CreditAccount,
    CreditAdjustment,
    CreditLedgerEntry,
    CreditPackage,
    CreditPurchase,
    CreditPurchaseCoupon,
    CreditRate,
)
from rest_framework import serializers


class CreditAccountSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)
    academy_name = serializers.CharField(source='academy.name', read_only=True)

    class Meta:
        model = CreditAccount
        fields = [
            'id',
            'academy_id',
            'academy_name',
            'currency_unit',
            'balance',
            'total_credited',
            'total_debited',
            'status',
            'last_transaction_at',
            'created_at',
        ]
        read_only_fields = fields

class CreditLedgerEntrySerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)

    class Meta:
        model = CreditLedgerEntry
        fields = [
            'id',
            'entry_type',
            'source_type',
            'amount',
            'balance_before',
            'balance_after',
            'reference_type',
            'reference_id',
            'idempotency_key',
            'description',
            'metadata',
            'created_by_email',
            'occurred_at',
        ]
        read_only_fields = fields

class CreditRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditRate
        fields = [
            'id',
            'feature_key',
            'name',
            'description',
            'billing_type',
            'unit_size',
            'credit_cost',
            'price',
            'credits',
            'currency',
            'is_purchasable',
            'is_active',
            'created_at',
        ]

    def validate_currency(self, value):
        from core.utils import normalize_currency
        return normalize_currency(value)

class CreditPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditPackage
        fields = [
            'id',
            'name',
            'description',
            'credits',
            'price',
            'currency',
            'bonus_credits',
            'popular',
            'is_active',
            'sort_order',
        ]

    def validate_currency(self, value):
        from core.utils import normalize_currency
        return normalize_currency(value)

class CreditPurchaseCouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditPurchaseCoupon
        fields = [
            'id',
            'code',
            'description',
            'discount_type',
            'discount_value',
            'min_purchase_amount',
            'max_discount_amount',
            'usage_limit',
            'current_usage_count',
            'valid_from',
            'valid_until',
            'is_active',
        ]

class CreditPurchaseSerializer(serializers.ModelSerializer):
    rate_name = serializers.CharField(source='rate.name', read_only=True, default='')
    package_name = serializers.CharField(source='package.name', read_only=True, default='')
    coupon_code = serializers.CharField(source='coupon.code', read_only=True, default='')

    class Meta:
        model = CreditPurchase
        fields = [
            'id',
            'rate',
            'rate_name',
            'package',
            'package_name',
            'coupon',
            'coupon_code',
            'base_credits',
            'bonus_credits',
            'total_credits',
            'original_price',
            'discount_amount',
            'final_price',
            'currency',
            'payment_order_id',
            'payment_transaction_id',
            'status',
            'fulfilled_at',
            'created_at',
        ]
        read_only_fields = fields

class CreatePurchaseRequestSerializer(serializers.Serializer):
    rate_id = serializers.UUIDField(required=False, allow_null=True)
    package_id = serializers.UUIDField(required=False, allow_null=True)
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')

class ApplyCouponRequestSerializer(serializers.Serializer):
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')
    rate_id = serializers.UUIDField(required=False, allow_null=True)
    package_id = serializers.UUIDField(required=False, allow_null=True)

class FulfillPurchaseRequestSerializer(serializers.Serializer):
    payment_transaction_id = serializers.CharField(required=False, allow_blank=True, default='')

class CreditAdjustmentSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='account.academy.id', read_only=True)
    requested_by_email = serializers.EmailField(source='requested_by.email', read_only=True)
    approved_by_email = serializers.EmailField(source='approved_by.email', read_only=True)

    class Meta:
        model = CreditAdjustment
        fields = [
            'id',
            'academy_id',
            'adjustment_type',
            'amount',
            'reason',
            'status',
            'requested_by_email',
            'approved_by_email',
            'created_at',
        ]
        read_only_fields = fields

class ManualAdjustmentRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=6)
    adjustment_type = serializers.ChoiceField(choices=AdjustmentType.choices, default=AdjustmentType.ADD)
    reason = serializers.CharField()

class ReversalRequestSerializer(serializers.Serializer):
    reason = serializers.CharField()

class MonthlyBillingLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        from credits.models import MonthlyBillingLineItem
        model = MonthlyBillingLineItem
        fields = [
            'id',
            'item_type',
            'feature_code',
            'description',
            'quantity',
            'unit',
            'rate',
            'credits',
            'metadata'
        ]

class MonthlyBillingInvoiceSerializer(serializers.ModelSerializer):
    line_items = MonthlyBillingLineItemSerializer(many=True, read_only=True)
    billing_period_label = serializers.CharField(source='billing_period.period_start', read_only=True)

    class Meta:
        from credits.models import MonthlyBillingInvoice
        model = MonthlyBillingInvoice
        fields = [
            'id',
            'billing_period',
            'billing_period_label',
            'total_credits',
            'status',
            'generated_at',
            'finalized_at',
            'line_items'
        ]

