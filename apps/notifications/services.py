import logging

from django.utils import timezone

from notifications.models import (
    DeliveryChannel,
    DeliveryStatus,
    EmailSuppression,
    Notification,
    NotificationDelivery,
)

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def send_email(to_email: str, subject: str, body: str, template_name: str = "base", context: dict = None, **kwargs):
        logger.info(f"Queuing email for {to_email}: {subject}")
        from emails.outbox_service import EmailJobService
        ctx = dict(context or {})
        ctx.setdefault("body", body)
        return EmailJobService.create_transactional_job(
            recipient_email=to_email,
            subject=subject,
            template_name=template_name or "base",
            context=ctx,
        )

    @classmethod
    def send_transactional(cls, recipient: str, template_code: str, subject: str, context: dict = None, user=None, academy=None, idempotency_key: str = None, **kwargs):
        from emails.outbox_service import EmailJobService

        email_normalized = recipient.lower().strip()
        if EmailSuppression.objects.filter(email_normalized=email_normalized, is_active=True).exists():
            acad = academy or (getattr(user, 'academy', None) if user else None)
            return NotificationDelivery.objects.create(
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.SUPPRESSED,
                recipient_email=recipient,
                subject_snapshot=subject,
                recipient_user=user,
                academy=acad,
                template_code=template_code,
                idempotency_key=idempotency_key,
            )

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
    def notify_user(
        cls,
        recipient,
        notification_type: str,
        title: str,
        message: str,
        action_type: str = "LINK",
        action_url: str = "",
        source_type: str = "",
        source_id: str = "",
        academy=None,
        channels=None,
        idempotency_key: str = None,
    ):
        logger.info(f"Notification sent to user {recipient}: {title} - {message}")
        if channels is None:
            channels = [DeliveryChannel.IN_APP]

        if idempotency_key:
            existing_delivery = (
                NotificationDelivery.objects.filter(idempotency_key=idempotency_key)
                .select_related('notification')
                .first()
            )
            if existing_delivery and existing_delivery.notification_id:
                return existing_delivery.notification

        if source_type and source_id:
            existing = Notification.objects.filter(
                recipient=recipient,
                source_type=source_type,
                source_id=source_id,
                deleted_at__isnull=True
            ).first()
            if existing:
                return existing

        resolved_academy = academy or getattr(recipient, 'academy', None)
        notification = Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            action_type=action_type,
            action_url=action_url,
            source_type=source_type,
            source_id=source_id,
            academy=resolved_academy,
        )

        now = timezone.now()
        store_idempotency_on_in_app = (
            idempotency_key
            and DeliveryChannel.IN_APP in channels
        )

        if DeliveryChannel.IN_APP in channels:
            NotificationDelivery.objects.create(
                notification=notification,
                channel=DeliveryChannel.IN_APP,
                status=DeliveryStatus.DELIVERED,
                recipient_user=recipient,
                academy=resolved_academy,
                delivered_at=now,
                idempotency_key=idempotency_key if store_idempotency_on_in_app else None,
            )

        if DeliveryChannel.EMAIL in channels:
            recipient_email = getattr(recipient, 'email', '') or ''
            email_normalized = recipient_email.lower().strip()
            suppressed = EmailSuppression.objects.filter(
                email_normalized=email_normalized,
                is_active=True,
            ).exists()

            if suppressed:
                NotificationDelivery.objects.create(
                    notification=notification,
                    channel=DeliveryChannel.EMAIL,
                    status=DeliveryStatus.SUPPRESSED,
                    recipient_email=recipient_email,
                    subject_snapshot=title,
                    recipient_user=recipient,
                    academy=resolved_academy,
                    template_code=notification_type,
                )
            else:
                EmailService.send_transactional(
                    recipient=recipient_email,
                    template_code=notification_type,
                    subject=title,
                    context={'body': message},
                    user=recipient,
                    academy=resolved_academy,
                )
                NotificationDelivery.objects.create(
                    notification=notification,
                    channel=DeliveryChannel.EMAIL,
                    status=DeliveryStatus.QUEUED,
                    recipient_email=recipient_email,
                    subject_snapshot=title,
                    recipient_user=recipient,
                    academy=resolved_academy,
                    template_code=notification_type,
                    queued_at=now,
                    idempotency_key=(
                        idempotency_key
                        if idempotency_key and not store_idempotency_on_in_app
                        else None
                    ),
                )

        return notification

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

