import logging

from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, subject: str, recipient: str, message_body: str):
    """
    Legacy entrypoint wrapper delegating to canonical EmailJobService outbox.
    """
    try:
        from emails.outbox_service import EmailJobService
        job = EmailJobService.create_transactional_job(
            recipient_email=recipient,
            subject=subject,
            template_name="base",
            context={"body": message_body}
        )
        logger.info(f"Delegated legacy authentication send_email_task to EmailJob {job.id}")
        return str(job.id)
    except Exception as exc:
        logger.error(f"Failed to queue email job for {recipient}: {exc!s}")
        raise self.retry(exc=exc)
