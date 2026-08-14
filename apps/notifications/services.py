import logging
from notifications.models import Notification

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def send_email(to_email: str, subject: str, body: str):
        logger.info(f"Sending email to {to_email}: {subject}")
        return True

    @classmethod
    def send_transactional(cls, recipient: str, template_code: str, subject: str, context: dict = None, user=None, academy=None, idempotency_key: str = None, **kwargs):
        body = context.get('body', subject) if context else subject
        return cls.send_email(to_email=recipient, subject=subject, body=body)


class NotificationService:
    @classmethod
    def notify_user(cls, recipient, notification_type: str, title: str, message: str, action_type: str = "LINK", action_url: str = "", source_type: str = "", source_id: str = "", academy=None):
        logger.info(f"Notification sent to user {recipient}: {title} - {message}")
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
        notification = Notification.objects.get(id=notification_id, user=user)
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return notification

    @staticmethod
    def mark_all_as_read(user):
        return Notification.objects.filter(user=user, is_read=False).update(is_read=True)

    @staticmethod
    def soft_delete_notification(notification_id, user):
        notification = Notification.objects.get(id=notification_id, user=user)
        notification.delete()
        return notification

