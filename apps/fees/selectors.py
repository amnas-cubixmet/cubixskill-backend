from decimal import Decimal
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus
from fees.models import (
    StudentFeeAccount,
    StudentFeeAccountStatus,
    FeeInstallment,
    InstallmentStatus,
    FeePayment,
)

class FeeCollectionAnalyticsSelector:

    @classmethod
    def get_course_fee_summary(cls, course) -> dict:
        """
        Calculates authoritative course fee collection statistics directly from database records.
        """
        enrolled_students_count = Enrollment.objects.filter(
            course=course,
            status=EnrollmentStatus.ACTIVE
        ).count()

        accounts = StudentFeeAccount.objects.filter(course=course)
        configured_students_count = accounts.count()

        total_expected = sum(acc.effective_fee_amount for acc in accounts) or Decimal('0.00')

        payments = FeePayment.objects.filter(course=course, status='COMPLETED')
        total_collected = sum(p.amount for p in payments) or Decimal('0.00')

        outstanding = max(Decimal('0.00'), total_expected - total_collected)

        today = timezone.now().date()
        overdue_installments = FeeInstallment.objects.filter(
            fee_account__course=course,
            due_date__lt=today,
            status__in=[InstallmentStatus.OVERDUE, InstallmentStatus.PARTIAL, InstallmentStatus.UPCOMING, InstallmentStatus.DUE]
        )
        overdue_amount = sum(
            max(Decimal('0.00'), inst.amount - inst.paid_amount - inst.waived_amount)
            for inst in overdue_installments
        ) or Decimal('0.00')

        paid_count = accounts.filter(status=StudentFeeAccountStatus.PAID).count()
        partial_count = accounts.filter(status=StudentFeeAccountStatus.PARTIAL).count()
        pending_count = accounts.filter(status=StudentFeeAccountStatus.PENDING).count()
        overdue_count = accounts.filter(status=StudentFeeAccountStatus.OVERDUE).count()
        not_configured_count = max(0, enrolled_students_count - configured_students_count)

        return {
            "course_id": str(course.id),
            "course_title": course.title,
            "total_students": enrolled_students_count,
            "configured_students": configured_students_count,
            "total_expected": float(total_expected),
            "total_collected": float(total_collected),
            "outstanding_balance": float(outstanding),
            "overdue_amount": float(overdue_amount),
            "paid_count": paid_count,
            "partial_count": partial_count,
            "pending_count": pending_count,
            "overdue_count": overdue_count,
            "not_configured_count": not_configured_count,
            "currency": "INR"
        }
