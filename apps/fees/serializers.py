from fees.models import (
    CourseDefaultFeePlan,
    FeeAdjustment,
    FeeInstallment,
    FeePayment,
    StudentFeeAccount,
)
from rest_framework import serializers


class FeeInstallmentSerializer(serializers.ModelSerializer):
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = FeeInstallment
        fields = [
            'id', 'sequence', 'label', 'due_date', 'amount',
            'paid_amount', 'waived_amount', 'remaining_amount', 'status'
        ]

    def get_remaining_amount(self, obj):
        return float(max(0, obj.amount - obj.paid_amount - obj.waived_amount))


class FeePaymentSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source='recorded_by.full_name', read_only=True, default='Admin')

    class Meta:
        model = FeePayment
        fields = [
            'id', 'receipt_number', 'amount', 'currency', 'payment_date',
            'collection_mode', 'payment_method', 'reference_number',
            'gateway_order_id', 'gateway_payment_id', 'notes', 'status', 'recorded_by_name'
        ]


class FeeAdjustmentSerializer(serializers.ModelSerializer):
    authorized_by_name = serializers.CharField(source='authorized_by.full_name', read_only=True, default='Admin')

    class Meta:
        model = FeeAdjustment
        fields = [
            'id', 'adjustment_type', 'amount', 'reason', 'authorized_by_name', 'created_at'
        ]


class StudentFeeAccountSerializer(serializers.ModelSerializer):
    installments = FeeInstallmentSerializer(many=True, read_only=True)
    payments = FeePaymentSerializer(many=True, read_only=True)
    adjustments = FeeAdjustmentSerializer(many=True, read_only=True)

    class Meta:
        model = StudentFeeAccount
        fields = [
            'id', 'academy', 'course', 'student', 'enrollment', 'plan_type',
            'currency', 'total_fee_amount', 'effective_fee_amount', 'start_date',
            'status', 'notes', 'installments', 'payments', 'adjustments'
        ]


class CourseDefaultFeePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseDefaultFeePlan
        fields = ['id', 'course', 'plan_type', 'total_fee', 'currency', 'number_of_installments']
