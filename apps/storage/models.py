#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import BaseModel
from users_roles.models import User

#--------------------------------------------------------------
# Enums
#--------------------------------------------------------------

class MediaType(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    AUDIO = 'AUDIO', 'Audio'
    DOCUMENT = 'DOCUMENT', 'Document'
    OTHER = 'OTHER', 'Other'

class MediaStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    ACTIVE = 'ACTIVE', 'Active'
    DELETED = 'DELETED', 'Deleted'
    FAILED = 'FAILED', 'Failed'

class UploadSessionStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    UPLOADED = 'UPLOADED', 'Uploaded'
    CONFIRMED = 'CONFIRMED', 'Confirmed'
    EXPIRED = 'EXPIRED', 'Expired'
    FAILED = 'FAILED', 'Failed'

class ProcessingStatus(models.TextChoices):
    UPLOADED = 'UPLOADED', 'Uploaded'
    QUEUED = 'QUEUED', 'Queued'
    PROCESSING = 'PROCESSING', 'Processing'
    READY = 'READY', 'Ready'
    FAILED = 'FAILED', 'Failed'

class ProcessingMode(models.TextChoices):
    HLS = 'hls', 'HLS'
    DIRECT = 'direct', 'Direct'

class UsageEventType(models.TextChoices):
    UPLOAD = 'UPLOAD', 'Upload'
    DELETE = 'DELETE', 'Delete'
    REPLACE = 'REPLACE', 'Replace'
    RESTORE = 'RESTORE', 'Restore'
    BASELINE = 'BASELINE', 'Baseline'
    ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'
    RECONCILIATION = 'RECONCILIATION', 'Reconciliation'
    STREAMING_GENERATED = 'STREAMING_GENERATED', 'Streaming Generated'

class BillingStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    CALCULATED = 'CALCULATED', 'Calculated'
    PENDING_CHARGE = 'PENDING_CHARGE', 'Pending Charge'
    CHARGED = 'CHARGED', 'Charged'
    INSUFFICIENT_CREDITS = 'INSUFFICIENT_CREDITS', 'Insufficient Credits'
    FAILED = 'FAILED', 'Failed'
    REVERSED = 'REVERSED', 'Reversed'

# --------------------------------------------------------------
# 1. MediaFile Model
# --------------------------------------------------------------

class MediaFile(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    uploaded_by_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    course_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    lesson_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    original_filename = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default='')
    stored_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512, unique=True, db_index=True, default='')
    relative_path = models.CharField(max_length=512)

    file_type = models.CharField(max_length=50, blank=True, default='')
    mime_type = models.CharField(max_length=100)
    file_extension = models.CharField(max_length=20, blank=True, default='')
    size_bytes = models.BigIntegerField(default=0)
    storage_provider = models.CharField(max_length=50, default='local')
    storage_path = models.CharField(max_length=512, blank=True, default='')
    file_url = models.CharField(max_length=1024, blank=True, default='')
    checksum = models.CharField(max_length=128, blank=True, default='')

    media_type = models.CharField(max_length=20, choices=MediaType.choices, default=MediaType.OTHER)
    status = models.CharField(max_length=20, choices=MediaStatus.choices, default=MediaStatus.PENDING, db_index=True)

    # Video Adaptive HLS Streaming Fields
    adaptive_streaming_enabled = models.BooleanField(default=True)
    processing_mode = models.CharField(max_length=20, choices=ProcessingMode.choices, default=ProcessingMode.DIRECT, db_index=True)
    processing_status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.READY, db_index=True)
    processing_progress = models.IntegerField(default=100)
    processing_error = models.TextField(blank=True, default='')
    processed_at = models.DateTimeField(null=True, blank=True)

    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)

    source_size_bytes = models.BigIntegerField(default=0)
    streaming_size_bytes = models.BigIntegerField(default=0)
    stream_manifest_key = models.CharField(max_length=512, blank=True, default='')

    uploaded_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_media_files'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} ({self.media_type})"

    @property
    def total_storage_bytes(self) -> int:
        return self.size_bytes + self.streaming_size_bytes


# --------------------------------------------------------------
# HLS Streaming Profiles & Rendition Models
# --------------------------------------------------------------

class StorageStreamingProfile(BaseModel):
    quality_label = models.CharField(max_length=20, unique=True) # e.g. 1080p, 720p, 480p, 360p, 240p, 144p
    height = models.IntegerField()
    width = models.IntegerField()
    video_bitrate_kbps = models.IntegerField()
    audio_bitrate_kbps = models.IntegerField(default=128)
    is_enabled = models.BooleanField(default=True)
    order_index = models.IntegerField(default=0)

    class Meta:
        db_table = 'storage_streaming_profiles'
        ordering = ['-height']

    def __str__(self):
        return f"Profile {self.quality_label} ({self.width}x{self.height} @ {self.video_bitrate_kbps}k)"


class VideoRendition(BaseModel):
    media_file = models.ForeignKey(MediaFile, on_delete=models.CASCADE, related_name='renditions')
    quality_label = models.CharField(max_length=20)
    height = models.IntegerField()
    width = models.IntegerField()
    video_bitrate_kbps = models.IntegerField()
    audio_bitrate_kbps = models.IntegerField(default=128)
    playlist_key = models.CharField(max_length=512)
    size_bytes = models.BigIntegerField(default=0)
    status = models.CharField(max_length=20, default='READY')

    class Meta:
        db_table = 'storage_video_renditions'
        ordering = ['-height']

    def __str__(self):
        return f"Rendition {self.quality_label} for {self.media_file.original_filename}"


#--------------------------------------------------------------
# 2. UploadSession Model
#--------------------------------------------------------------

class UploadSession(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    requested_by_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    storage_key = models.CharField(max_length=512, db_index=True)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    expected_size_bytes = models.BigIntegerField()
    purpose = models.CharField(max_length=100, default='GENERAL')

    status = models.CharField(max_length=20, choices=UploadSessionStatus.choices, default=UploadSessionStatus.PENDING)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_upload_sessions'

    def __str__(self):
        return f"Upload Session: {self.original_name} ({self.status})"

#--------------------------------------------------------------
# 3. AcademyStorageAccount Model
#--------------------------------------------------------------

class AcademyStorageAccount(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, unique=True, db_index=True)
    current_usage_bytes = models.BigIntegerField(default=0)
    storage_limit_bytes = models.BigIntegerField(null=True, blank=True)
    billing_enabled = models.BooleanField(default=True)
    metering_enabled_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_academy_accounts'

    def __str__(self):
        return f"Storage Account: {self.academy_uuid} ({self.current_usage_bytes} bytes)"

#--------------------------------------------------------------
# 4. StorageUsageEvent Model (Immutable Ledger)
#--------------------------------------------------------------

class StorageUsageEvent(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    media_file = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, null=True, blank=True, related_name='storage_events')
    media_file_uuid_snapshot = models.UUIDField(null=True, blank=True)

    original_filename_snapshot = models.CharField(max_length=255, blank=True, default='')
    file_type_snapshot = models.CharField(max_length=50, blank=True, default='')
    mime_type_snapshot = models.CharField(max_length=100, blank=True, default='')

    event_type = models.CharField(max_length=30, choices=UsageEventType.choices, default=UsageEventType.UPLOAD, db_index=True)
    delta_bytes = models.BigIntegerField(default=0)
    storage_before_bytes = models.BigIntegerField(default=0)
    storage_after_bytes = models.BigIntegerField(default=0)
    usage_after_bytes = models.BigIntegerField(default=0)
    file_size_bytes = models.BigIntegerField(default=0)

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    performed_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True)
    source = models.CharField(max_length=50, default='MEDIA_LIBRARY')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'storage_usage_events'
        ordering = ['occurred_at']
        indexes = [
            models.Index(fields=['academy_uuid', 'occurred_at']),
            models.Index(fields=['academy_uuid', 'event_type']),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.academy_uuid}]: {self.delta_bytes} bytes at {self.occurred_at}"

#--------------------------------------------------------------
# 5. StorageUsageRollup Model (Derived Optimization)
#--------------------------------------------------------------

class StorageUsageRollup(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    period_start = models.DateTimeField(default=timezone.now, db_index=True)
    period_end = models.DateTimeField(default=timezone.now, db_index=True)
    interval_type = models.CharField(max_length=20, default='DAILY')

    opening_bytes = models.BigIntegerField(default=0)
    closing_bytes = models.BigIntegerField(default=0)
    peak_bytes = models.BigIntegerField(default=0)

    uploaded_bytes = models.BigIntegerField(default=0)
    deleted_bytes = models.BigIntegerField(default=0)
    byte_seconds = models.BigIntegerField(default=0)

    upload_count = models.IntegerField(default=0)
    delete_count = models.IntegerField(default=0)

    calculated_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default='FINALIZED')

    class Meta:
        db_table = 'storage_usage_rollups'
        unique_together = ('academy_uuid', 'period_start', 'period_end', 'interval_type')
        ordering = ['-period_start']

    def __str__(self):
        return f"Rollup [{self.interval_type}]: {self.academy_uuid} ({self.period_start} to {self.period_end})"

#--------------------------------------------------------------
# 6. StorageMonthlyBilling Model (Durable Monthly Record)
#--------------------------------------------------------------

class StorageMonthlyBilling(BaseModel):
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    billing_period = models.CharField(max_length=20, db_index=True) # e.g. '2026-08'
    billing_period_start = models.DateTimeField(db_index=True)
    billing_period_end = models.DateTimeField(db_index=True)

    opening_bytes = models.BigIntegerField(default=0)
    closing_bytes = models.BigIntegerField(default=0)
    peak_bytes = models.BigIntegerField(default=0)

    total_uploaded_bytes = models.BigIntegerField(default=0)
    total_deleted_bytes = models.BigIntegerField(default=0)
    total_byte_seconds = models.BigIntegerField(default=0)

    billable_units_gb_month = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal('0.000000'))
    rate_snapshot = models.JSONField(default=dict, blank=True)

    credits_calculated = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    credits_charged = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))

    status = models.CharField(max_length=30, choices=BillingStatus.choices, default=BillingStatus.OPEN, db_index=True)
    credit_transaction = models.ForeignKey(
        'credits.CreditLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='storage_billing_records'
    )

    calculated_at = models.DateTimeField(null=True, blank=True)
    charged_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'storage_monthly_billings'
        unique_together = ('academy_uuid', 'billing_period')
        ordering = ['-billing_period_start']

    def __str__(self):
        return f"Monthly Billing [{self.academy_uuid} - {self.billing_period}]: {self.credits_charged} Credits ({self.status})"

#--------------------------------------------------------------
# 7. StoragePricingRule Model
#--------------------------------------------------------------

class StoragePricingRule(BaseModel):
    name = models.CharField(max_length=100)
    credits_per_gb_hour = models.DecimalField(max_digits=12, decimal_places=6, default=0.001)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'storage_pricing_rules'

    def __str__(self):
        return f"Pricing Rule: {self.name} ({self.credits_per_gb_hour} credits/GB-hour)"
