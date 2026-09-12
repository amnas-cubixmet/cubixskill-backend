import logging

from notifications.models import Notification

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def send_email(to_email: str, subject: str, body: str):
        logger.info(f"Queuing email for {to_email}: {subject}")
        from emails.outbox_service import EmailJobService
        return EmailJobService.create_transactional_job(
            recipient_email=to_email,
            subject=subject,
            template_name="base",
            context={"body": body}
        )

    @classmethod
    def send_transactional(cls, recipient: str, template_code: str, subject: str, context: dict = None, user=None, academy=None, idempotency_key: str = None, **kwargs):
        from emails.outbox_service import EmailJobService
        ctx = context or {}
        body = ctx.get('body', subject)
        ctx['body'] = body
        template_map = {
            "ACADEMY_ACCOUNT_SETUP": "academy_activation",
            "PASSWORD_RESET": "password_reset",
            "PASSWORD_CHANGED": "password_changed",
            "EMAIL_VERIFICATION": "verification"
        }
        template_name = template_map.get(template_code, "base")
        acad_id = academy.id if academy else (getattr(user, 'academy_id', None) if user else None)
        u_id = user.id if user else None
        u_name = getattr(user, 'full_name', '') if user else ''
        return EmailJobService.create_transactional_job(
            recipient_email=recipient,
            subject=subject,
            template_name=template_name,
            context=ctx,
            academy_uuid=acad_id,
            recipient_user_uuid=u_id,
            recipient_name=u_name,
            idempotency_key=idempotency_key
        )


class NotificationService:
    @classmethod
    def notify_user(cls, recipient, notification_type: str, title: str, message: str, action_type: str = "LINK", action_url: str = "", source_type: str = "", source_id: str = "", academy=None):
        logger.info(f"Notification sent to user {recipient}: {title} - {message}")
        if source_type and source_id:
            existing = Notification.objects.filter(
                recipient=recipient,
                source_type=source_type,
                source_id=source_id,
                deleted_at__isnull=True
            ).first()
            if existing:
                return existing

        return Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            action_type=action_type,
            action_url=action_url,
            source_type=source_type,
            source_id=source_id,
            academy=academy
        )

    @staticmethod
    def mark_as_read(notification_id, user):
        from django.utils import timezone
        notification = Notification.objects.get(id=notification_id, recipient=user)
        if not notification.read_at:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])
        return notification

    @staticmethod
    def mark_all_as_read(user, academy_id=None):
        from django.utils import timezone
        qs = Notification.objects.filter(recipient=user, read_at__isnull=True, deleted_at__isnull=True)
        if academy_id:
            qs = qs.filter(academy_id=academy_id)
        return qs.update(read_at=timezone.now())

    @staticmethod
    def soft_delete_notification(notification_id, user):
        from django.utils import timezone
        notification = Notification.objects.get(id=notification_id, recipient=user)
        notification.deleted_at = timezone.now()
        notification.save(update_fields=['deleted_at'])
        return notification

