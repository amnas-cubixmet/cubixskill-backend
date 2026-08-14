#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

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

class UsageEventType(models.TextChoices):
    FILE_ADDED = 'FILE_ADDED', 'File Added'
    FILE_REMOVED = 'FILE_REMOVED', 'File Removed'
    FILE_REPLACED = 'FILE_REPLACED', 'File Replaced'
    ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'
    RECONCILIATION = 'RECONCILIATION', 'Reconciliation'

# --------------------------------------------------------------
# 1. MediaFile Model
# Physical files are stored locally during development.
# Business apps depend on MediaFile rather than filesystem paths.
# Deleting a file affects future usage only; historical usage is preserved.
# --------------------------------------------------------------

class MediaFile(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='media_files', null=True, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='uploaded_media_files')

    original_filename = models.CharField(max_length=255)
    stored_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512, unique=True, db_index=True, default='')
    relative_path = models.CharField(max_length=512)

    mime_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField(default=0)
    media_type = models.CharField(max_length=20, choices=MediaType.choices, default=MediaType.OTHER)
    status = models.CharField(max_length=20, choices=MediaStatus.choices, default=MediaStatus.PENDING, db_index=True)

    uploaded_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_media_files'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} ({self.media_type})"

#--------------------------------------------------------------
# 2. UploadSession Model
#--------------------------------------------------------------

class UploadSession(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='upload_sessions', null=True, blank=True)
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='upload_sessions', null=True, blank=True)

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
    academy = models.OneToOneField('academy.Academy', on_delete=models.CASCADE, related_name='storage_account')
    current_usage_bytes = models.BigIntegerField(default=0)
    storage_limit_bytes = models.BigIntegerField(null=True, blank=True)
    billing_enabled = models.BooleanField(default=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_academy_accounts'

    def __str__(self):
        return f"Storage Account: {self.academy.name} ({self.current_usage_bytes} bytes)"

#--------------------------------------------------------------
# 4. StorageUsageEvent Model
#--------------------------------------------------------------

class StorageUsageEvent(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='storage_events', null=True, blank=True)
    media_file = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, null=True, blank=True, related_name='storage_events')

    event_type = models.CharField(max_length=30, choices=UsageEventType.choices, default=UsageEventType.FILE_ADDED)
    delta_bytes = models.BigIntegerField()
    usage_after_bytes = models.BigIntegerField(default=0)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'storage_usage_events'
        ordering = ['occurred_at']

    def __str__(self):
        return f"{self.event_type}: {self.delta_bytes} bytes for {self.academy.name}"

#--------------------------------------------------------------
# 5. StorageUsageSnapshot Model
#--------------------------------------------------------------

class StorageUsageSnapshot(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='storage_snapshots', null=True, blank=True)
    period_start = models.DateTimeField(default=timezone.now, db_index=True)
    period_end = models.DateTimeField(default=timezone.now, db_index=True)

    opening_usage_bytes = models.BigIntegerField(default=0)
    closing_usage_bytes = models.BigIntegerField(default=0)
    byte_hours = models.DecimalField(max_digits=24, decimal_places=2, default=0.0)
    gb_hours = models.DecimalField(max_digits=16, decimal_places=4, default=0.0)
    average_usage_bytes = models.BigIntegerField(default=0)

    calculated_at = models.DateTimeField(default=timezone.now)
    calculation_version = models.CharField(max_length=20, default='v1')
    status = models.CharField(max_length=20, default='FINALIZED')

    class Meta:
        db_table = 'storage_usage_snapshots'
        unique_together = ('academy', 'period_start', 'period_end')
        ordering = ['-period_start']

    def __str__(self):
        return f"Snapshot: {self.academy.name} ({self.period_start} to {self.period_end})"

#--------------------------------------------------------------
# 6. StoragePricingRule Model
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
