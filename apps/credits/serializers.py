from rest_framework import serializers
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditAdjustment,
    LedgerEntryType,
    CreditSourceType,
    AdjustmentType,
)

# --------------------------------------------------------------
# Credit Serializers
# Serializes wallet balances, immutable ledger entries, and admin adjustments.
# --------------------------------------------------------------

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
