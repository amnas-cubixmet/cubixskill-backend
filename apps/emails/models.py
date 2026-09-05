import uuid
from django.db import models
from django.utils import timezone
from core.models import BaseModel

class EmailJobStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    PROCESSING = 'PROCESSING', 'Processing'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class EmailJobType(models.TextChoices):
    TRANSACTIONAL = 'TRANSACTIONAL', 'Transactional Email'
    LIVE_SESSION_CREATED_EMAIL = 'LIVE_SESSION_CREATED_EMAIL', 'Live Session Created Email'
    LIVE_SESSION_REMINDER_EMAIL = 'LIVE_SESSION_REMINDER_EMAIL', 'Live Session 1-Hour Reminder'
    LIVE_SESSION_UPDATED_EMAIL = 'LIVE_SESSION_UPDATED_EMAIL', 'Live Session Updated Email'
    LIVE_SESSION_CANCELLED_EMAIL = 'LIVE_SESSION_CANCELLED_EMAIL', 'Live Session Cancelled Email'
    GENERAL_NOTIFICATION = 'GENERAL_NOTIFICATION', 'General Email Notification'


class EmailJob(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    job_type = models.CharField(
        max_length=60,
        choices=EmailJobType.choices,
        default=EmailJobType.GENERAL_NOTIFICATION,
        db_index=True
    )
    reference_type = models.CharField(max_length=100, blank=True, default='')
    reference_id = models.UUIDField(null=True, blank=True, db_index=True)

    subject = models.CharField(max_length=255, blank=True, default='')
    template_name = models.CharField(max_length=100, blank=True, default='')

    scheduled_for = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=EmailJobStatus.choices,
        default=EmailJobStatus.PENDING,
        db_index=True
    )

    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    last_error = models.TextField(blank=True, default='')
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)

    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'emails_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_for']),
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['academy_uuid', 'created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f"EmailJob {self.job_type} [{self.status}] (Scheduled: {self.scheduled_for})"


class EmailRecipientDelivery(BaseModel):
    job = models.ForeignKey(EmailJob, on_delete=models.CASCADE, related_name='recipient_deliveries')
    recipient_email = models.EmailField(db_index=True)
    recipient_user_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    status = models.CharField(
        max_length=20,
        choices=EmailJobStatus.choices,
        default=EmailJobStatus.PENDING,
        db_index=True
    )
    provider_message_id = models.CharField(max_length=255, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'emails_recipient_deliveries'
        ordering = ['created_at']
        unique_together = ('job', 'recipient_email')

    def __str__(self):
        return f"Delivery {self.recipient_email} [{self.status}] for Job {self.job_id}"
