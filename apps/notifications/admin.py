from django.contrib import admin
from notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    NotificationBatch,
    EmailSuppression,
)

# --------------------------------------------------------------
# Notifications Admin Registration
# --------------------------------------------------------------

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'notification_type', 'title', 'priority', 'read_at', 'deleted_at', 'created_at']
    list_filter = ['notification_type', 'priority']
    search_fields = ['recipient__email', 'title', 'message', 'source_id']

@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ['channel', 'status', 'recipient_email', 'template_code', 'provider', 'attempt_count', 'sent_at']
    list_filter = ['channel', 'status', 'provider']
    search_fields = ['recipient_email', 'idempotency_key', 'provider_message_id']

@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification_type', 'in_app_enabled', 'email_enabled', 'push_enabled']
    search_fields = ['user__email', 'notification_type']

@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'channel', 'is_active', 'is_mandatory', 'version']
    list_filter = ['channel', 'is_active', 'is_mandatory']
    search_fields = ['code', 'name']

@admin.register(NotificationBatch)
class NotificationBatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'academy', 'notification_type', 'status', 'recipient_count', 'sent_count', 'failed_count', 'created_at']
    list_filter = ['status', 'notification_type']
    search_fields = ['title', 'academy__name']

@admin.register(EmailSuppression)
class EmailSuppressionAdmin(admin.ModelAdmin):
    list_display = ['email_normalized', 'reason', 'source', 'is_active', 'suppressed_at']
    list_filter = ['reason', 'is_active']
    search_fields = ['email_normalized']
