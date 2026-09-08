from decimal import Decimal

from core.models import BaseModel
from django.db import models
from django.utils import timezone
from payments.models import PaymentMethod

# --------------------------------------------------------------
# Student Fee Collection Domain Enums & Models
# Dedicated app for student fee accounting, installment scheduling,
# payment tracking, receipts, waivers, and collection ledger.
# --------------------------------------------------------------

class StudentFeePlanType(models.TextChoices):
    ONE_TIME = 'ONE_TIME', 'One-Time Payment'
    WEEKLY = 'WEEKLY', 'Weekly Installments'
    MONTHLY = 'MONTHLY', 'Monthly Installments'
    QUARTERLY = 'QUARTERLY', 'Quarterly Installments'
    HALF_YEARLY = 'HALF_YEARLY', 'Half-Yearly Installments'
    YEARLY = 'YEARLY', 'Yearly Installments'
    CUSTOM = 'CUSTOM', 'Custom Schedule'


class StudentFeeAccountStatus(models.TextChoices):
    NOT_CONFIGURED = 'NOT_CONFIGURED', 'Not Configured'
    UNPAID = 'UNPAID', 'Unpaid'
    PENDING = 'PENDING', 'Pending'
    PARTIAL = 'PARTIAL', 'Partial'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    PAID = 'PAID', 'Paid'
    OVERDUE = 'OVERDUE', 'Overdue'
    WAIVED = 'WAIVED', 'Waived'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CollectionMode(models.TextChoices):
    CUBIXSKILL_GATEWAY = 'CUBIXSKILL_GATEWAY', 'CubixSkill Gateway'
    DIRECT_ACADEMY = 'DIRECT_ACADEMY', 'Direct Academy'


class InstallmentStatus(models.TextChoices):
    UPCOMING = 'UPCOMING', 'Upcoming'
    DUE = 'DUE', 'Due'
    PARTIAL = 'PARTIAL', 'Partial'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    PAID = 'PAID', 'Paid'
    OVERDUE = 'OVERDUE', 'Overdue'
    WAIVED = 'WAIVED', 'Waived'
    CANCELLED = 'CANCELLED', 'Cancelled'


class StudentFeeAccount(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='fee_accounts', db_index=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='fee_accounts', db_index=True)
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, related_name='fee_accounts', db_index=True)
    enrollment = models.ForeignKey('enrollments.Enrollment', on_delete=models.SET_NULL, null=True, blank=True, related_name='fee_accounts')

    plan_type = models.CharField(max_length=20, choices=StudentFeePlanType.choices, default=StudentFeePlanType.ONE_TIME)
    currency = models.CharField(max_length=10, default='INR')
    total_fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    effective_fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    start_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=StudentFeeAccountStatus.choices, default=StudentFeeAccountStatus.UNPAID, db_index=True)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'student_fee_accounts'
        unique_together = ('course', 'student')
        ordering = ['-created_at']

    def __str__(self):
        return f"FeeAccount [{self.student.email} - {self.course.title}] ({self.status})"


class FeeInstallment(BaseModel):
    fee_account = models.ForeignKey(StudentFeeAccount, on_delete=models.CASCADE, related_name='installments', db_index=True)
    sequence = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=100, default='Installment 1')
    due_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    waived_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=InstallmentStatus.choices, default=InstallmentStatus.UPCOMING, db_index=True)

    class Meta:
        db_table = 'fee_installments'
        ordering = ['due_date', 'sequence']

    def __str__(self):
        return f"{self.label} - {self.fee_account.student.email} ({self.status})"


class FeePayment(BaseModel):
    fee_account = models.ForeignKey(StudentFeeAccount, on_delete=models.CASCADE, related_name='payments', db_index=True)
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, related_name='fee_payments', db_index=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='fee_payments', db_index=True)

    receipt_number = models.CharField(max_length=100, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    payment_date = models.DateField(default=timezone.now, db_index=True)
    collection_mode = models.CharField(max_length=30, choices=CollectionMode.choices, default=CollectionMode.DIRECT_ACADEMY, db_index=True)
    payment_method = models.CharField(max_length=30, choices=PaymentMethod.choices, default=PaymentMethod.UPI)
    reference_number = models.CharField(max_length=100, blank=True, default='')
    gateway_order_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    gateway_payment_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    gateway_signature = models.CharField(max_length=512, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, default='COMPLETED', db_index=True)
    recorded_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'fee_payments'
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"Receipt {self.receipt_number} - {self.amount} ({self.payment_method})"


class FeePaymentAllocation(BaseModel):
    payment = models.ForeignKey(FeePayment, on_delete=models.CASCADE, related_name='allocations', db_index=True)
    installment = models.ForeignKey(FeeInstallment, on_delete=models.CASCADE, related_name='allocations', db_index=True)
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'fee_payment_allocations'

    def __str__(self):
        return f"Allocation {self.allocated_amount} for Payment {self.payment.receipt_number}"


class FeeAdjustment(BaseModel):
    fee_account = models.ForeignKey(StudentFeeAccount, on_delete=models.CASCADE, related_name='adjustments', db_index=True)
    adjustment_type = models.CharField(max_length=20, default='WAIVER')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    authorized_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'fee_adjustments'
        ordering = ['-created_at']

    def __str__(self):
        return f"Adjustment {self.adjustment_type} - {self.amount} ({self.fee_account.student.email})"


class CourseDefaultFeePlan(BaseModel):
    course = models.OneToOneField('courses.Course', on_delete=models.CASCADE, related_name='default_fee_plan')
    plan_type = models.CharField(max_length=20, choices=StudentFeePlanType.choices, default=StudentFeePlanType.ONE_TIME)
    total_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=10, default='INR')
    number_of_installments = models.PositiveIntegerField(default=1)

    start_date = models.DateField(default=timezone.now)
    custom_installments = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'course_default_fee_plans'

    def __str__(self):
        return f"Default Fee Plan [{self.course.title}] ({self.plan_type} - {self.total_fee})"
