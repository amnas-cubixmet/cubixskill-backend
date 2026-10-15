#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from decimal import Decimal

from rest_framework import serializers
from storage.models import (
    AcademyStorageAccount,
    MediaFile,
    StorageMonthlyBilling,
    StorageUsageEvent,
    StorageUsageRollup,
    VideoRendition,
)

#--------------------------------------------------------------
# MediaFile Serializer
#--------------------------------------------------------------

class VideoRenditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoRendition
        fields = ['quality_label', 'width', 'height', 'video_bitrate_kbps', 'audio_bitrate_kbps', 'playlist_key', 'size_bytes', 'status']

class MediaFileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    stream_url = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    usage_count = serializers.SerializerMethodField()
    total_storage_bytes = serializers.ReadOnlyField()
    renditions = VideoRenditionSerializer(many=True, read_only=True)

    class Meta:
        model = MediaFile
        fields = [
            'id', 'original_filename', 'display_name', 'stored_filename',
            'storage_key', 'relative_path', 'mime_type', 'file_type', 'file_extension',
            'size_bytes', 'source_size_bytes', 'streaming_size_bytes', 'total_storage_bytes',
            'media_type', 'status', 'adaptive_streaming_enabled', 'processing_mode', 'processing_status', 'processing_progress', 'processing_error',
            'processed_at', 'duration_seconds', 'width', 'height', 'stream_manifest_key',
            'url', 'stream_url', 'renditions', 'created_at', 'updated_at', 'uploaded_at',
            'uploaded_by_uuid', 'course_uuid', 'lesson_uuid', 'usage_count'
        ]
        read_only_fields = fields

    def get_display_name(self, obj):
        return obj.display_name or obj.original_filename

    def get_usage_count(self, obj):
        from storage.selectors import MediaUsageSelector
        return MediaUsageSelector.get_usage(obj).get('usage_count', 0)

    def get_url(self, obj):
        if not obj.storage_key:
            return ""
        return f"/media/{obj.storage_key.lstrip('/')}"

    def get_stream_url(self, obj):
        if not obj.stream_manifest_key:
            return ""
        return f"/media/{obj.stream_manifest_key.lstrip('/')}"


class PreUploadEstimateRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255, required=True)
    file_size_bytes = serializers.IntegerField(required=True, min_value=0)
    mime_type = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    duration_seconds = serializers.FloatField(required=False, allow_null=True)
    width = serializers.IntegerField(required=False, allow_null=True)
    height = serializers.IntegerField(required=False, allow_null=True)
    adaptive_streaming_enabled = serializers.BooleanField(required=False, default=True)


class DirectUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)

class UpdateMediaFileSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    original_filename = serializers.CharField(max_length=255, required=False)
    display_name = serializers.CharField(max_length=255, required=False)
    mime_type = serializers.CharField(max_length=100, required=False)

#--------------------------------------------------------------
# Upload Session Serializers
#--------------------------------------------------------------

class UploadUrlRequestSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(max_length=100)
    file_size_bytes = serializers.IntegerField(min_value=1)
    purpose = serializers.CharField(max_length=100, required=False, default='GENERAL')

class UploadUrlResponseSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField()
    upload_url = serializers.CharField()
    storage_key = serializers.CharField()
    expires_in = serializers.IntegerField(default=900)

#--------------------------------------------------------------
# Storage Account & Rollup Serializers
#--------------------------------------------------------------

class StorageAccountSummarySerializer(serializers.ModelSerializer):
    current_usage_gb = serializers.SerializerMethodField()

    class Meta:
        model = AcademyStorageAccount
        fields = ['current_usage_bytes', 'current_usage_gb', 'billing_enabled', 'last_reconciled_at']

    def get_current_usage_gb(self, obj):
        return round(obj.current_usage_bytes / (1024 * 1024 * 1024), 4)

class StorageUsageRollupSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageUsageRollup
        fields = [
            'id', 'interval_type', 'period_start', 'period_end',
            'opening_bytes', 'closing_bytes', 'peak_bytes',
            'uploaded_bytes', 'deleted_bytes', 'byte_seconds',
            'upload_count', 'delete_count', 'status', 'calculated_at'
        ]

class StorageMonthlyBillingSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageMonthlyBilling
        fields = [
            'id', 'billing_period', 'billing_period_start', 'billing_period_end',
            'opening_bytes', 'closing_bytes', 'peak_bytes',
            'total_uploaded_bytes', 'total_deleted_bytes', 'total_byte_seconds',
            'billable_units_gb_month', 'rate_snapshot',
            'credits_calculated', 'credits_charged', 'status',
            'calculated_at', 'charged_at', 'error_message'
        ]

class StorageUsageEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageUsageEvent
        fields = [
            'id', 'media_file_uuid_snapshot', 'original_filename_snapshot',
            'file_type_snapshot', 'mime_type_snapshot', 'event_type',
            'delta_bytes', 'storage_before_bytes', 'storage_after_bytes',
            'file_size_bytes', 'occurred_at', 'source', 'metadata'
        ]


class StorageBillingSettingsUpdateSerializer(serializers.Serializer):
    """Explicit platform-admin input; reject negative/unbounded pricing."""
    storage_billing_enabled = serializers.BooleanField(required=False)
    storage_billing_interval = serializers.ChoiceField(
        choices=["10_SECONDS", "6_HOURS", "12_HOURS", "18_HOURS", "1_DAY"],
        required=False,
    )
    storage_credit_rate_per_gb = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0.0000"),
        max_value=Decimal("1000000.0000"), required=False,
    )
    storage_credit_debit_day = serializers.IntegerField(min_value=1, max_value=31, required=False)
    storage_credit_debit_time = serializers.TimeField(required=False)

    def validate_storage_billing_interval(self, value):
        from django.conf import settings
        if value == "10_SECONDS" and not settings.DEBUG:
            raise serializers.ValidationError("10-second billing is available in development mode only.")
        return value


class StorageBillingSettingsSerializer(serializers.ModelSerializer):
    storage_billing_enabled = serializers.BooleanField(source='billing_enabled')
    billing_interval_label = serializers.SerializerMethodField()

    class Meta:
        from storage.models import StorageBillingSettings
        model = StorageBillingSettings
        fields = [
            'id', 'storage_billing_enabled', 'billing_enabled', 'storage_billing_interval',
            'storage_credit_rate_per_gb', 'billing_interval_label', 'is_active', 'updated_at'
        ]

    def get_billing_interval_label(self, obj):
        from storage.utils import get_interval_label
        return get_interval_label(obj.storage_billing_interval)


class StorageUsageChargeSerializer(serializers.ModelSerializer):
    storage_gb = serializers.SerializerMethodField()
    used_gb = serializers.SerializerMethodField()
    credit_rate_per_gb = serializers.SerializerMethodField()
    rate_per_gb = serializers.SerializerMethodField()
    credits_debited = serializers.SerializerMethodField()
    charged_credits = serializers.SerializerMethodField()
    billing_interval = serializers.CharField(source='interval')
    billing_interval_label = serializers.SerializerMethodField()
    interval_label = serializers.SerializerMethodField()
    debited_at = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        from storage.models import StorageUsageCharge
        model = StorageUsageCharge
        fields = [
            'id', 'billing_started_at', 'billing_ended_at', 'interval', 'billing_interval',
            'interval_label', 'billing_interval_label', 'used_bytes', 'used_gb', 'storage_gb',
            'rate_per_gb', 'credit_rate_per_gb', 'charged_credits', 'credits_debited',
            'status', 'debited_at', 'created_at'
        ]

    def get_storage_gb(self, obj):
        return f"{Decimal(obj.used_bytes) / Decimal(1024 ** 3):.2f}"

    def get_used_gb(self, obj):
        return self.get_storage_gb(obj)

    def get_credit_rate_per_gb(self, obj):
        return f"{obj.rate_per_gb:.4f}"

    def get_rate_per_gb(self, obj):
        return f"{obj.rate_per_gb:.4f}"

    def get_credits_debited(self, obj):
        if obj.status in ['SUCCESS', 'CHARGED'] and (obj.ledger_entry or obj.charged_credits == Decimal("0.0000")):
            return f"-{obj.charged_credits:.4f}" if obj.charged_credits > 0 else "0.0000"
        return "0.0000"

    def get_charged_credits(self, obj):
        return f"{obj.charged_credits:.4f}"

    def get_interval_label(self, obj):
        from storage.utils import get_interval_label
        return get_interval_label(obj.interval)

    def get_billing_interval_label(self, obj):
        return self.get_interval_label(obj)

    def get_status(self, obj):
        if obj.status in ['SUCCESS', 'CHARGED'] and (obj.ledger_entry or obj.charged_credits == Decimal("0.0000")):
            return "SUCCESS"
        return "FAILED"

    def get_debited_at(self, obj):
        ts = obj.debited_at
        return ts.isoformat() if ts else None


class AcademyStorageSnapshotSerializer(serializers.ModelSerializer):
    used_gb = serializers.SerializerMethodField()

    class Meta:
        from storage.models import AcademyStorageSnapshot
        model = AcademyStorageSnapshot
        fields = ['id', 'captured_at', 'used_bytes', 'used_gb', 'file_count', 'source']

    def get_used_gb(self, obj):
        return f"{Decimal(obj.used_bytes) / Decimal(1024 ** 3):.2f}"


class StorageBillingPeriodSerializer(serializers.ModelSerializer):
    average_used_gb = serializers.SerializerMethodField()
    peak_used_gb = serializers.SerializerMethodField()
    free_storage_gb = serializers.SerializerMethodField()
    billable_storage_gb = serializers.SerializerMethodField()

    class Meta:
        from storage.models import StorageBillingPeriod
        model = StorageBillingPeriod
        fields = [
            'id', 'period_start', 'period_end', 'status', 'billing_method',
            'average_used_bytes', 'average_used_gb', 'peak_used_bytes', 'peak_used_gb',
            'free_storage_bytes', 'free_storage_gb', 'billable_storage_bytes', 'billable_storage_gb',
            'credits_per_gb_month', 'credits_charged', 'closed_at'
        ]

    def get_average_used_gb(self, obj):
        return f"{Decimal(obj.average_used_bytes) / Decimal(1024 ** 3):.2f}"

    def get_peak_used_gb(self, obj):
        return f"{Decimal(obj.peak_used_bytes) / Decimal(1024 ** 3):.2f}"

    def get_free_storage_gb(self, obj):
        return f"{Decimal(obj.free_storage_bytes) / Decimal(1024 ** 3):.2f}"

    def get_billable_storage_gb(self, obj):
        return f"{Decimal(obj.billable_storage_bytes) / Decimal(1024 ** 3):.2f}"


class StorageMeterRecordSerializer(serializers.ModelSerializer):
    metering_interval_label = serializers.SerializerMethodField()

    class Meta:
        from storage.models import StorageMeterRecord
        model = StorageMeterRecord
        fields = [
            'id', 'metered_at', 'used_bytes', 'used_gb',
            'credit_rate_per_gb', 'calculated_credits',
            'metering_interval', 'metering_interval_label', 'created_at'
        ]

    def get_metering_interval_label(self, obj):
        from storage.utils import get_interval_label
        return get_interval_label(obj.metering_interval)


class StorageBillingCycleSerializer(serializers.ModelSerializer):
    meter_record_count = serializers.ReadOnlyField()
    credits_debited = serializers.SerializerMethodField()
    credits_paid = serializers.SerializerMethodField()
    storage_billed = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()

    class Meta:
        from storage.models import StorageBillingCycle
        model = StorageBillingCycle
        fields = [
            'id', 'cycle_start_at', 'cycle_end_at', 'status', 'settlement_status',
            'accumulated_credits', 'original_amount', 'paid_amount', 'outstanding_amount',
            'storage_billed', 'credits_paid', 'outstanding', 'credits_debited',
            'meter_record_count', 'debited_at', 'settled_at', 'created_at'
        ]

    def get_credits_debited(self, obj):
        return f"{obj.paid_amount:.4f}"

    def get_credits_paid(self, obj):
        return f"{obj.paid_amount:.4f}"

    def get_storage_billed(self, obj):
        return f"{obj.original_amount:.4f}"

    def get_outstanding(self, obj):
        return f"{obj.outstanding_amount:.4f}"

