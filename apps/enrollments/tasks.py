from celery import shared_task
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus
from enrollments.services import EnrollmentService


@shared_task
def expire_enrollments_task():
    """
    Background Celery task to auto-expire enrollments past their expiration date.
    """
    now = timezone.now()
    expired_enrollments = Enrollment.objects.filter(
        status=EnrollmentStatus.ACTIVE,
        is_lifetime=False,
        access_expires_at__lte=now
    )

    count = 0
    for enrollment in expired_enrollments:
        try:
            EnrollmentService.expire_enrollment(enrollment, reason="Auto-expired by background Celery task")
            count += 1
        except Exception:
            pass

    return f"Successfully expired {count} enrollments."

@shared_task
def send_expiry_notifications_task():
    """
    Background Celery task to identify upcoming enrollment expirations.
    """
    now = timezone.now()
    seven_days_hence = now + timezone.timedelta(days=7)

    expiring_soon = Enrollment.objects.filter(
        status=EnrollmentStatus.ACTIVE,
        is_lifetime=False,
        access_expires_at__range=(now, seven_days_hence)
    )

    return f"Identified {expiring_soon.count()} enrollments expiring soon."
