import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from enrollments.models import Enrollment, EnrollmentStatus
from fees.models import CourseDefaultFeePlan
from fees.services import FeeAccountService

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Enrollment)
def auto_configure_student_fee_account_on_enrollment(sender, instance, created, **kwargs):
    """
    When a student is enrolled in a course that has an active default fee plan,
    automatically create their StudentFeeAccount with the course's default schedule.
    """
    if instance.status != EnrollmentStatus.ACTIVE or not instance.student or not instance.course:
        return

    try:
        default_plan = CourseDefaultFeePlan.objects.filter(course=instance.course).first()
        if default_plan:
            FeeAccountService.configure_student_fee_account(
                student=instance.student,
                course=instance.course,
                plan_type=default_plan.plan_type,
                total_fee_amount=default_plan.total_fee,
                start_date=default_plan.start_date,
                currency=default_plan.currency,
                number_of_installments=default_plan.number_of_installments,
                custom_installments=default_plan.custom_installments,
                notes=default_plan.notes
            )
    except Exception as e:
        logger.error(f"Failed to auto-configure fee account for student {instance.student_id} on course {instance.course_id}: {e}")
