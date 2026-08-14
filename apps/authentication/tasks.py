import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, subject: str, recipient: str, message_body: str):
    try:
        send_mail(
            subject=subject,
            message=message_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com'),
            recipient_list=[recipient],
            fail_silently=False
        )
        logger.info(f"Email successfully sent to {recipient}")
    except Exception as exc:
        logger.error(f"Failed to send email to {recipient}: {str(exc)}")
        raise self.retry(exc=exc)
