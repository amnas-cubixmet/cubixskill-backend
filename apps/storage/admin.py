#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.contrib import admin
from storage.models import (
    AcademyStorageAccount,
    MediaFile,
    StorageMonthlyBilling,
    StoragePricingRule,
    StorageUsageEvent,
    StorageUsageRollup,
    UploadSession,
)

#--------------------------------------------------------------
# Admin Configuration
#--------------------------------------------------------------

@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'media_type', 'size_bytes', 'status', 'academy_uuid', 'uploaded_at')
    list_filter = ('media_type', 'status')
    search_fields = ('original_filename', 'storage_key', 'mime_type')

@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'purpose', 'status', 'academy_uuid', 'expires_at')
    list_filter = ('status',)

@admin.register(AcademyStorageAccount)
class AcademyStorageAccountAdmin(admin.ModelAdmin):
    list_display = ('academy_uuid', 'current_usage_bytes', 'billing_enabled', 'last_reconciled_at')

@admin.register(StorageUsageEvent)
class StorageUsageEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'delta_bytes', 'storage_before_bytes', 'storage_after_bytes', 'academy_uuid', 'occurred_at')
    list_filter = ('event_type',)

@admin.register(StorageUsageRollup)
class StorageUsageRollupAdmin(admin.ModelAdmin):
    list_display = ('academy_uuid', 'interval_type', 'period_start', 'period_end', 'byte_seconds', 'status')
    list_filter = ('interval_type', 'status')

@admin.register(StorageMonthlyBilling)
class StorageMonthlyBillingAdmin(admin.ModelAdmin):
    list_display = ('academy_uuid', 'billing_period', 'billable_units_gb_month', 'credits_charged', 'status', 'charged_at')
    list_filter = ('status', 'billing_period')

@admin.register(StoragePricingRule)
class StoragePricingRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'credits_per_gb_hour', 'effective_from', 'is_active')
