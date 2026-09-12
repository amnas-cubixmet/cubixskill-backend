from core.models import BaseModel
from django.db import models
from django.utils import timezone
from users_roles.models import User

# --------------------------------------------------------------
# Notification Enums & Choices
# Stable machine-readable constants for channels, priorities, and types.
# --------------------------------------------------------------

class DeliveryChannel(models.TextChoices):
    IN_APP = 'IN_APP', 'In-App Notification'
    EMAIL = 'EMAIL', 'Email Notification'
    PUSH = 'PUSH', 'Push Notification'

class NotificationPriority(models.TextChoices):
    LOW = 'LOW', 'Low'
    NORMAL = 'NORMAL', 'Normal'
    HIGH = 'HIGH', 'High'
    CRITICAL = 'CRITICAL', 'Critical'

class NotificationType(models.TextChoices):
    LIVE_SESSION_CREATED = 'LIVE_SESSION_CREATED', 'Live Session Created'
    LIVE_SESSION_STARTING_SOON = 'LIVE_SESSION_STARTING_SOON', 'Live Session Starting Soon'
    LIVE_SESSION_CANCELLED = 'LIVE_SESSION_CANCELLED', 'Live Session Cancelled'
    COURSE_ENROLLED = 'COURSE_ENROLLED', 'Course Enrolled'
    COURSE_COMPLETED = 'COURSE_COMPLETED', 'Course Completed'
    PAYMENT_SUCCESS = 'PAYMENT_SUCCESS', 'Payment Success'
    PAYMENT_FAILED = 'PAYMENT_FAILED', 'Payment Failed'
    PAYMENT_REFUNDED = 'PAYMENT_REFUNDED', 'Payment Refunded'
    CERTIFICATE_ISSUED = 'CERTIFICATE_ISSUED', 'Certificate Issued'
    LEAD_ASSIGNED = 'LEAD_ASSIGNED', 'Lead Assigned'
    LEAD_FOLLOW_UP_DUE = 'LEAD_FOLLOW_UP_DUE', 'Lead Follow-Up Due'
    CREDIT_BALANCE_LOW = 'CREDIT_BALANCE_LOW', 'Credit Balance Low'
    CHAT_MENTION = 'CHAT_MENTION', 'Chat Mention'
    DISCUSSION_REPLY = 'DISCUSSION_REPLY', 'Discussion Reply'
    ANNOUNCEMENT_PUBLISHED = 'ANNOUNCEMENT_PUBLISHED', 'Announcement Published'

class EmailCategory(models.TextChoices):
    TRANSACTIONAL = 'TRANSACTIONAL', 'Transactional'
    BULK = 'BULK', 'Bulk'

class DeliveryStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    PROCESSING = 'PROCESSING', 'Processing'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    FAILED = 'FAILED', 'Failed'
    SUPPRESSED = 'SUPPRESSED', 'Suppressed'
    CANCELLED = 'CANCELLED', 'Cancelled'

class SuppressionReason(models.TextChoices):
    HARD_BOUNCE = 'HARD_BOUNCE', 'Hard Bounce'
    COMPLAINT = 'COMPLAINT', 'Spam Complaint'
    UNSUBSCRIBED = 'UNSUBSCRIBED', 'Unsubscribed'
    INVALID_ADDRESS = 'INVALID_ADDRESS', 'Invalid Address'
    ADMIN_BLOCK = 'ADMIN_BLOCK', 'Admin Block'

class BatchStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    PARTIAL = 'PARTIAL', 'Partially Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'

# --------------------------------------------------------------
# Notification Delivery
# Persist notifications before realtime delivery.
# WebSocket delivery failure must not lose the stored notification.
# Email delivery is separate from in-app notification state.
# Transactional and bulk email must remain isolated.
# NotificationPreference controls optional delivery choices.
# EmailSuppression must block invalid, bounced, complained, or unsubscribed recipients.
# Celery handles asynchronous email delivery and retries.
# Idempotency must prevent duplicate delivery attempts.
# Notification data must respect Academy/User access boundaries.
# Multi-device read/delete state must remain backend-authoritative.
# --------------------------------------------------------------

class Notification(BaseModel):
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True
    )
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )

    notification_type = models.CharField(
        max_length=100,
        choices=NotificationType.choices,
        default=NotificationType.LIVE_SESSION_STARTING_SOON,
        db_index=True
    )

    title = models.CharField(max_length=255)
    message = models.TextField()

    action_type = models.CharField(max_length=50, blank=True, default='')  # LINK, NAVIGATE, MODAL
    action_url = models.CharField(max_length=500, blank=True, default='')

    source_type = models.CharField(max_length=50, blank=True, default='', db_index=True)
    source_id = models.CharField(max_length=255, blank=True, default='')

    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True
    )

    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read_at']),
            models.Index(fields=['recipient', 'deleted_at']),
            models.Index(fields=['source_type', 'source_id']),
        ]

    def __str__(self):
        return f"Notification [{self.notification_type}] for {self.recipient.email}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

# --------------------------------------------------------------
# 2. NotificationDelivery Model
# Tracks channel delivery state (In-App, Email, Push) independently.
# Retains provider message IDs and failure codes.
# --------------------------------------------------------------

class NotificationDelivery(BaseModel):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='deliveries'
    )
    channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.EMAIL,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True
    )

    recipient_email = models.EmailField(blank=True, default='', db_index=True)
    subject_snapshot = models.CharField(max_length=255, blank=True, default='')
    recipient_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deliveries'
    )
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deliveries'
    )

    template_code = models.CharField(max_length=100, blank=True, default='', db_index=True)
    provider = models.CharField(max_length=50, default='CONSOLE')
    provider_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)

    attempt_count = models.PositiveIntegerField(default=0)

    queued_at = models.DateTimeField(null=True, blank=True)
    processing_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    failure_code = models.CharField(max_length=100, blank=True, default='')
    failure_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'notification_deliveries'
        ordering = ['-created_at']

    def __str__(self):
        return f"Delivery [{self.channel}] {self.recipient_email or self.recipient_user_id} - ({self.status})"

# --------------------------------------------------------------
# 3. NotificationPreference Model
# User channel preferences per notification category.
# Mandatory security/payment notices bypass user disablement.
# --------------------------------------------------------------

class NotificationPreference(BaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    notification_type = models.CharField(max_length=100, db_index=True)

    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_preferences'
        unique_together = ('user', 'notification_type')

    def __str__(self):
        return f"Preference {self.user.email} - {self.notification_type}"

# --------------------------------------------------------------
# 4. NotificationTemplate Model
# Reusable template configurations for email and in-app rendering.
# Placeholders are safely rendered server-side.
# --------------------------------------------------------------

class NotificationTemplate(BaseModel):
    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)

    channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.EMAIL
    )

    subject_template = models.CharField(max_length=255)
    title_template = models.CharField(max_length=255, blank=True, default='')
    html_template = models.TextField()
    text_template = models.TextField()

    is_active = models.BooleanField(default=True)
    is_mandatory = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'notification_templates'
        ordering = ['code']

    def __str__(self):
        return f"Template {self.name} ({self.code})"

# --------------------------------------------------------------
# 5. NotificationBatch Model
# Tracks large multi-recipient broadcast notifications.
# Processed in rate-controlled Celery chunks to protect email quotas.
# --------------------------------------------------------------

class NotificationBatch(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notification_batches'
    )
    notification_type = models.CharField(max_length=100)

    title = models.CharField(max_length=255)
    message = models.TextField()
    channel_config = models.JSONField(default=dict, blank=True)

    recipient_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=BatchStatus.choices,
        default=BatchStatus.DRAFT,
        db_index=True
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    processed_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    suppressed_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'notification_batches'
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch {self.id} [{self.notification_type}] - ({self.status})"

# --------------------------------------------------------------
# 6. EmailSuppression Model
# Suppresses hard bounces, spam complaints, and unsubscribed emails.
# Protects sender domain reputation and deliverability quotas.
# --------------------------------------------------------------

class EmailSuppression(BaseModel):
    email_normalized = models.EmailField(unique=True, db_index=True)
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_suppressions'
    )

    reason = models.CharField(
        max_length=30,
        choices=SuppressionReason.choices,
        default=SuppressionReason.HARD_BOUNCE
    )
    source = models.CharField(max_length=100, blank=True, default='SYSTEM')

    is_active = models.BooleanField(default=True)
    suppressed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'email_suppressions'
        ordering = ['-suppressed_at']

    def __str__(self):
        return f"Suppression {self.email_normalized} ({self.reason})"
