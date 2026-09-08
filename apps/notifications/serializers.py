from notifications.models import (
    Notification,
    NotificationBatch,
    NotificationPreference,
)
from rest_framework import serializers


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'title',
            'message',
            'action_type',
            'action_url',
            'source_type',
            'source_id',
            'priority',
            'read_at',
            'is_read',
            'created_at',
        ]
        read_only_fields = fields

class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'notification_type',
            'in_app_enabled',
            'email_enabled',
            'push_enabled',
        ]

class NotificationBatchSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)

    class Meta:
        model = NotificationBatch
        fields = [
            'id',
            'academy_id',
            'notification_type',
            'title',
            'message',
            'recipient_count',
            'status',
            'processed_count',
            'sent_count',
            'failed_count',
            'suppressed_count',
            'scheduled_at',
            'started_at',
            'completed_at',
            'created_at',
        ]
        read_only_fields = fields
