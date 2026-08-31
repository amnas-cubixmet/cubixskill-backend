#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from rest_framework import serializers
from storage.models import (
    MediaFile, AcademyStorageAccount, StorageUsageEvent,
    StorageUsageRollup, StorageMonthlyBilling, VideoRendition
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
