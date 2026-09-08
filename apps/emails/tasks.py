import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from emails.models import EmailJob, EmailJobStatus

logger = logging.getLogger(__name__)

@shared_task(bind=True, ignore_result=True, max_retries=3, default_retry_delay=60)
def process_email_job_task(self, job_id: str):
    """
    Celery Worker task to execute durable EmailJob delivery.
    """
    from django.conf import settings
    logger.info(f"Executing process_email_job_task for job_id={job_id} using EMAIL_HOST={getattr(settings, 'EMAIL_HOST', 'None')}")
    try:
        from emails.outbox_service import EmailJobService
        result = EmailJobService.process_email_job(job_id)
        logger.info(f"EmailJob {job_id} processing result: {result}")
        return f"EmailJob {job_id} processed. Result: {result}"
    except Exception as exc:
        logger.error(f"Error in process_email_job_task for job {job_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@shared_task(ignore_result=True)
def dispatch_pending_email_jobs():

    """
    Celery Beat periodic task: Scans PostgreSQL DB outbox for due EmailJobs
    and enqueues process_email_job_task for execution.
    Uses select_for_update(skip_locked=True) for safe concurrency across multiple workers.
    """
    now = timezone.now()
    dispatched_count = 0

    with transaction.atomic():
        pending_jobs = list(
            EmailJob.objects.select_for_update(skip_locked=True).filter(
                status__in=[EmailJobStatus.PENDING, EmailJobStatus.QUEUED],
                scheduled_for__lte=now
            ).filter(
                models_q_filter(now)
            )[:100]
        )

        for job in pending_jobs:
            job.status = EmailJobStatus.QUEUED
            job.save(update_fields=['status'])
            process_email_job_task.delay(str(job.id))
            dispatched_count += 1

    if dispatched_count > 0:
        logger.info(f"Dispatched {dispatched_count} due EmailJobs from DB outbox to Celery worker.")
    return f"Dispatched {dispatched_count} EmailJobs"


def models_q_filter(now):
    from django.db.models import Q
    return Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)


@shared_task(queue='default')
def cleanup_stuck_processing_jobs():
    """
    Reconciliation task: Resets jobs stuck in PROCESSING longer than 15 minutes
    due to worker crashes or force terminations back to PENDING.
    """
    threshold = timezone.now() - timedelta(minutes=15)
    stuck_jobs = EmailJob.objects.filter(
        status=EmailJobStatus.PROCESSING,
        started_at__lte=threshold
    )

    reset_count = 0
    for job in stuck_jobs:
        if job.attempt_count < job.max_attempts:
            job.status = EmailJobStatus.PENDING
            job.save(update_fields=['status'])
            reset_count += 1
        else:
            job.status = EmailJobStatus.FAILED
            job.last_error = "Job stuck in PROCESSING after worker crash. Max attempts reached."
            job.save(update_fields=['status', 'last_error'])

    if reset_count > 0:
        logger.warning(f"Reconciled {reset_count} stuck PROCESSING EmailJobs back to PENDING.")
    return f"Reconciled {reset_count} stuck jobs."


@shared_task
def test_email_delivery(recipient: str):
    from django.conf import settings
    from django.core.mail import send_mail

    logger.info(f"EMAIL_BACKEND={settings.EMAIL_BACKEND}")
    logger.info(f"EMAIL_HOST={settings.EMAIL_HOST}")
    logger.info(f"EMAIL_PORT={settings.EMAIL_PORT}")
    logger.info(f"EMAIL_HOST_USER={settings.EMAIL_HOST_USER}")
    logger.info(f"DEFAULT_FROM_EMAIL={settings.DEFAULT_FROM_EMAIL}")

    return send_mail(
        "CubixSkill Celery Test",
        "This email was sent from Celery.",
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=False,
    )

