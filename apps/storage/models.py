#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import datetime
import uuid
from decimal import Decimal

from core.models import BaseModel
from django.db import models
from django.utils import timezone

#--------------------------------------------------------------
# Enums
#--------------------------------------------------------------

class MediaType(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    AUDIO = 'AUDIO', 'Audio'
    DOCUMENT = 'DOCUMENT', 'Document'
    FONT = 'FONT', 'Font'
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

    @classmethod
    def ensure_default_profiles(cls):
        defaults = [
            {"quality_label": "1080p", "width": 1920, "height": 1080, "video_bitrate_kbps": 5000, "audio_bitrate_kbps": 128, "order_index": 1},
            {"quality_label": "720p",  "width": 1280, "height": 720,  "video_bitrate_kbps": 2800, "audio_bitrate_kbps": 128, "order_index": 2},
            {"quality_label": "480p",  "width": 854,  "height": 480,  "video_bitrate_kbps": 1400, "audio_bitrate_kbps": 128, "order_index": 3},
            {"quality_label": "360p",  "width": 640,  "height": 360,  "video_bitrate_kbps": 800,  "audio_bitrate_kbps": 128, "order_index": 4},
        ]
        for p in defaults:
            cls.objects.get_or_create(
                quality_label=p["quality_label"],
                defaults={
                    "width": p["width"],
                    "height": p["height"],
                    "video_bitrate_kbps": p["video_bitrate_kbps"],
                    "audio_bitrate_kbps": p["audio_bitrate_kbps"],
                    "is_enabled": True,
                    "order_index": p["order_index"],
                }
            )

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


#--------------------------------------------------------------
# 8. Storage Billing System Core Models
#--------------------------------------------------------------

class StorageBillingInterval(models.TextChoices):
    TEN_SECONDS = "10_SECONDS", "10 Seconds — Test"
    SIX_HOURS = "6_HOURS", "6 Hours"
    TWELVE_HOURS = "12_HOURS", "12 Hours"
    EIGHTEEN_HOURS = "18_HOURS", "18 Hours"
    ONE_DAY = "1_DAY", "1 Day"


class StorageBillingSettings(BaseModel):
    storage_billing_enabled = models.BooleanField(default=False)
    storage_billing_interval = models.CharField(
        max_length=20,
        choices=StorageBillingInterval.choices,
        default=StorageBillingInterval.TWELVE_HOURS
    )
    storage_credit_rate_per_gb = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1.0000")
    )
    storage_credit_debit_day = models.PositiveSmallIntegerField(default=1)
    storage_credit_debit_time = models.TimeField(default=datetime.time(0, 0))
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'storage_billing_settings'

    def __str__(self):
        return f"Storage Billing Settings (Enabled: {self.storage_billing_enabled}, Rate: {self.storage_credit_rate_per_gb} credits/GB, Interval: {self.storage_billing_interval}, Debit Day: {self.storage_credit_debit_day})"

    @property
    def storage_metering_interval(self):
        return self.storage_billing_interval

    @storage_metering_interval.setter
    def storage_metering_interval(self, val):
        self.storage_billing_interval = val

    @property
    def credit_debit_day(self):
        return self.storage_credit_debit_day

    @property
    def credit_debit_time(self):
        return self.storage_credit_debit_time

    @property
    def storage_credit_settlement_day(self):
        return self.storage_credit_debit_day

    @storage_credit_settlement_day.setter
    def storage_credit_settlement_day(self, val):
        self.storage_credit_debit_day = val

    @property
    def storage_credit_settlement_time(self):
        return self.storage_credit_debit_time

    @storage_credit_settlement_time.setter
    def storage_credit_settlement_time(self, val):
        self.storage_credit_debit_time = val

    @property
    def billing_enabled(self):
        return self.storage_billing_enabled

    @billing_enabled.setter
    def billing_enabled(self, value):
        self.storage_billing_enabled = bool(value)

    @property
    def meter_interval_hours(self):
        if self.storage_billing_interval == StorageBillingInterval.SIX_HOURS:
            return 6
        if self.storage_billing_interval == StorageBillingInterval.ONE_DAY:
            return 24
        return 12

    @property
    def free_storage_bytes(self):
        return 0

    @property
    def credits_per_gb_month(self):
        return self.storage_credit_rate_per_gb

    @classmethod
    def get_settings(cls):
        obj = cls.objects.filter(is_active=True).order_by('-updated_at').first()
        if not obj:
            obj = cls.objects.create(
                storage_billing_enabled=False,
                storage_billing_interval=StorageBillingInterval.TWELVE_HOURS,
                storage_credit_rate_per_gb=Decimal("1.0000"),
                storage_credit_debit_day=1,
                storage_credit_debit_time=datetime.time(0, 0),
                is_active=True,
            )
        return obj


class StorageBillingCycleStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    PROCESSING = 'PROCESSING', 'Processing'
    SETTLED = 'SETTLED', 'Settled'
    DEBITED = 'DEBITED', 'Debited'
    FAILED = 'FAILED', 'Failed'


class StorageSettlementStatus(models.TextChoices):
    PAID = 'PAID', 'Paid'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    UNPAID = 'UNPAID', 'Unpaid'


class StorageBillingCycle(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.PROTECT,
        related_name='storage_billing_cycles'
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    cycle_start_at = models.DateTimeField()
    cycle_end_at = models.DateTimeField(null=True, blank=True)

    accumulated_credits = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )

    original_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )

    paid_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )

    outstanding_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )

    settlement_status = models.CharField(
        max_length=20,
        choices=StorageSettlementStatus.choices,
        null=True,
        blank=True,
        db_index=True
    )

    status = models.CharField(
        max_length=20,
        choices=StorageBillingCycleStatus.choices,
        default=StorageBillingCycleStatus.OPEN,
        db_index=True
    )

    credit_transaction = models.OneToOneField(
        'credits.CreditLedgerEntry',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='storage_billing_cycle'
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True
    )

    debited_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_billing_cycles'
        ordering = ['-cycle_start_at']
        constraints = [
            models.UniqueConstraint(
                fields=['academy'],
                condition=models.Q(status='OPEN'),
                name='unique_open_storage_cycle_per_academy'
            )
        ]

    def __str__(self):
        return f"StorageBillingCycle [{self.academy_id}]: {self.status}/{self.settlement_status} (Original: {self.original_amount}, Paid: {self.paid_amount}, Outstanding: {self.outstanding_amount})"

    @property
    def meter_record_count(self):
        return self.meter_records.count()


class StorageSettlementPayment(BaseModel):
    settlement = models.ForeignKey(
        StorageBillingCycle,
        on_delete=models.PROTECT,
        related_name="payments"
    )
    ledger_entry = models.OneToOneField(
        'credits.CreditLedgerEntry',
        on_delete=models.PROTECT,
        related_name='storage_settlement_payment'
    )
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=4
    )
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'storage_settlement_payments'
        ordering = ['paid_at']

    def __str__(self):
        return f"StorageSettlementPayment [{self.settlement_id}]: {self.amount} credits at {self.paid_at}"



class StorageMeterRecord(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.PROTECT,
        related_name='storage_meter_records'
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    billing_cycle = models.ForeignKey(
        StorageBillingCycle,
        on_delete=models.PROTECT,
        related_name='meter_records'
    )
    metered_at = models.DateTimeField(default=timezone.now, db_index=True)
    used_bytes = models.BigIntegerField()
    used_gb = models.DecimalField(max_digits=18, decimal_places=6)
    credit_rate_per_gb = models.DecimalField(max_digits=12, decimal_places=4)
    calculated_credits = models.DecimalField(max_digits=18, decimal_places=4)
    metering_interval = models.CharField(
        max_length=20,
        default="12_HOURS",
        choices=StorageBillingInterval.choices
    )
    file_count = models.PositiveIntegerField(default=0, null=True, blank=True)

    class Meta:
        db_table = 'storage_meter_records'
        ordering = ['-metered_at']

    def __str__(self):
        return f"StorageMeterRecord [{self.academy_id}]: {self.used_gb} GB @ {self.credit_rate_per_gb} -> {self.calculated_credits} credits ({self.metering_interval})"

    @property
    def interval(self):
        return self.metering_interval


class AcademyStorageUsage(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name="storage_usage_record",
        null=True,
        blank=True
    )
    academy_uuid = models.UUIDField(null=True, blank=True, unique=True, db_index=True)
    used_bytes = models.BigIntegerField(default=0)
    file_count = models.PositiveBigIntegerField(default=0)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    last_billed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'storage_academy_usages'

    def __str__(self):
        acad = self.academy.name if self.academy else self.academy_uuid
        return f"Storage Usage [{acad}]: {self.used_bytes} bytes ({self.file_count} files)"

    @property
    def last_updated_at(self):
        return self.updated_at

    @property
    def last_metered_at(self):
        return self.last_billed_at

    @last_metered_at.setter
    def last_metered_at(self, val):
        self.last_billed_at = val


class StorageUsageCharge(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.PROTECT,
        related_name='storage_charges',
        null=True,
        blank=True
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    billing_started_at = models.DateTimeField()
    billing_ended_at = models.DateTimeField()

    interval = models.CharField(max_length=20)

    used_bytes = models.BigIntegerField()

    rate_per_gb = models.DecimalField(
        max_digits=12,
        decimal_places=4
    )

    charged_credits = models.DecimalField(
        max_digits=14,
        decimal_places=4
    )

    status = models.CharField(max_length=20, default='CHARGED')

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True
    )

    ledger_entry = models.ForeignKey(
        'credits.CreditLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='storage_charge_records'
    )

    class Meta:
        db_table = 'storage_usage_charges'
        ordering = ['-billing_ended_at']

    @property
    def debited_at(self):
        if self.status in ['SUCCESS', 'CHARGED'] and self.ledger_entry:
            return self.ledger_entry.occurred_at or self.ledger_entry.created_at
        return None

    def __str__(self):
        acad = self.academy.name if self.academy else self.academy_uuid
        return f"Storage Usage Charge [{acad}]: {self.charged_credits} Credits ({self.interval})"


class AcademyStorageSnapshot(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name="storage_snapshots",
        null=True,
        blank=True
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    captured_at = models.DateTimeField(default=timezone.now, db_index=True)
    used_bytes = models.BigIntegerField(default=0)
    file_count = models.PositiveBigIntegerField(default=0)
    source = models.CharField(max_length=32, default="SCHEDULED")

    class Meta:
        db_table = 'storage_academy_snapshots'
        indexes = [
            models.Index(fields=["academy", "captured_at"]),
            models.Index(fields=["academy_uuid", "captured_at"]),
        ]
        ordering = ['-captured_at']

    def __str__(self):
        acad = self.academy.name if self.academy else self.academy_uuid
        return f"Snapshot [{acad}] at {self.captured_at}: {self.used_bytes} bytes"


class AcademyStorageDailyUsage(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name="storage_daily_usages",
        null=True,
        blank=True
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    usage_date = models.DateField(db_index=True)

    average_used_bytes = models.BigIntegerField(default=0)
    peak_used_bytes = models.BigIntegerField(default=0)
    last_used_bytes = models.BigIntegerField(default=0)
    snapshot_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'storage_academy_daily_usages'
        constraints = [
            models.UniqueConstraint(
                fields=["academy", "usage_date"],
                name="unique_academy_storage_day"
            )
        ]
        ordering = ['-usage_date']

    def __str__(self):
        acad = self.academy.name if self.academy else self.academy_uuid
        return f"Daily Usage [{acad} - {self.usage_date}]: Avg {self.average_used_bytes} bytes"


class StorageBillingPeriod(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name="storage_billing_periods",
        null=True,
        blank=True
    )
    academy_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    period_start = models.DateField(db_index=True)
    period_end = models.DateField(db_index=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("OPEN", "Open"),
            ("PROCESSING", "Processing"),
            ("CLOSED", "Closed"),
            ("FAILED", "Failed"),
        ],
        default="OPEN",
        db_index=True
    )

    billing_method = models.CharField(max_length=32, default="AVERAGE_DAILY")
    average_used_bytes = models.BigIntegerField(default=0)
    peak_used_bytes = models.BigIntegerField(default=0)

    free_storage_bytes = models.BigIntegerField(default=0)
    billable_storage_bytes = models.BigIntegerField(default=0)

    credits_per_gb_month = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    credits_charged = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))

    closed_at = models.DateTimeField(null=True, blank=True)
    ledger_entry = models.ForeignKey(
        'credits.CreditLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='storage_billing_period_records'
    )

    class Meta:
        db_table = 'storage_billing_periods'
        constraints = [
            models.UniqueConstraint(
                fields=["academy", "period_start", "period_end"],
                name="unique_academy_storage_billing_period"
            )
        ]
        ordering = ['-period_start']

    def __str__(self):
        acad = self.academy.name if self.academy else self.academy_uuid
        return f"Storage Billing Period [{acad}: {self.period_start} to {self.period_end}] ({self.status}): {self.credits_charged} Credits"


class StorageMeterFileSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meter_record = models.ForeignKey('storage.StorageMeterRecord', on_delete=models.CASCADE, related_name='file_snapshots')
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='storage_file_snapshots')
    academy_uuid = models.UUIDField(db_index=True)
    media_file = models.ForeignKey('storage.MediaFile', on_delete=models.SET_NULL, null=True, blank=True, related_name='meter_snapshots')
    media_file_uuid = models.UUIDField(db_index=True)
    filename_snapshot = models.CharField(max_length=255)
    media_type_snapshot = models.CharField(max_length=50)
    size_bytes_snapshot = models.BigIntegerField(default=0)
    uploaded_at_snapshot = models.DateTimeField(null=True, blank=True)
    storage_key_snapshot = models.CharField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'storage_meter_file_snapshots'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['meter_record', 'media_file_uuid'], name='unique_meter_record_media_file_snapshot')
        ]

    def __str__(self):
        return f"File Snapshot [{self.filename_snapshot}] for meter {self.meter_record_id}"

