from django.contrib import admin
from fees.models import (
    StudentFeeAccount,
    FeeInstallment,
    FeePayment,
    FeePaymentAllocation,
    FeeAdjustment,
    CourseDefaultFeePlan,
)

@admin.register(StudentFeeAccount)
class StudentFeeAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'course', 'plan_type', 'total_fee_amount', 'effective_fee_amount', 'status', 'created_at')
    list_filter = ('status', 'plan_type', 'currency', 'created_at')
    search_fields = ('student__email', 'student__full_name', 'course__title')
    ordering = ('-created_at',)

@admin.register(FeeInstallment)
class FeeInstallmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'fee_account', 'sequence', 'label', 'due_date', 'amount', 'paid_amount', 'status')
    list_filter = ('status', 'due_date')
    search_fields = ('fee_account__student__email', 'label')

@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'student', 'course', 'amount', 'currency', 'payment_method', 'payment_date', 'status')
    list_filter = ('payment_method', 'status', 'payment_date')
    search_fields = ('receipt_number', 'student__email', 'reference_number')

@admin.register(FeePaymentAllocation)
class FeePaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'payment', 'installment', 'allocated_amount')

@admin.register(FeeAdjustment)
class FeeAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'fee_account', 'adjustment_type', 'amount', 'created_at')

@admin.register(CourseDefaultFeePlan)
class CourseDefaultFeePlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'course', 'plan_type', 'total_fee', 'number_of_installments')
