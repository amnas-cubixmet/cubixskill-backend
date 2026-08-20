#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from rest_framework import serializers
from storage.models import MediaFile, UploadSession, AcademyStorageAccount, StorageUsageSnapshot
from storage.s3_client import storage_client

#--------------------------------------------------------------
# MediaFile Serializer
#--------------------------------------------------------------

class MediaFileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = MediaFile
        fields = ['id', 'original_filename', 'stored_filename', 'storage_key', 'relative_path', 'mime_type', 'size_bytes', 'media_type', 'status', 'url', 'created_at']
        read_only_fields = fields

    def get_url(self, obj):
        if not obj.storage_key:
            return ""
        try:
            return storage_client.generate_presigned_download_url(obj.storage_key)
        except Exception:
            # Fall back to local Django media URL if MinIO is not running
            return f"/media/{obj.storage_key.lstrip('/')}"


class DirectUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)

class UpdateMediaFileSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    original_filename = serializers.CharField(max_length=255, required=False)
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
# Storage Usage & Account Serializer
#--------------------------------------------------------------

class StorageAccountSummarySerializer(serializers.ModelSerializer):
    current_usage_gb = serializers.SerializerMethodField()

    class Meta:
        model = AcademyStorageAccount
        fields = ['current_usage_bytes', 'current_usage_gb', 'storage_limit_bytes', 'billing_enabled', 'last_reconciled_at']

    def get_current_usage_gb(self, obj):
        return round(obj.current_usage_bytes / (1024 * 1024 * 1024), 2)

class StorageSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageUsageSnapshot
        fields = ['id', 'period_start', 'period_end', 'opening_usage_bytes', 'closing_usage_bytes', 'byte_hours', 'gb_hours', 'average_usage_bytes', 'status', 'calculated_at']
