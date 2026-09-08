from analytics_reports.models import AnalyticsSnapshot, ReportJob, SavedReport
from django.contrib import admin

# --------------------------------------------------------------
# Analytics & Reports Admin Registration
# Admin interfaces for AnalyticsSnapshot, ReportJob, and SavedReport.
# Allows Super Admin to inspect persisted snapshots and Celery export jobs.
# ReportJob tracks export generation status for asynchronous file tasks.
# SavedReport stores reusable report configuration for tenant staff.
# --------------------------------------------------------------


@admin.register(AnalyticsSnapshot)
class AnalyticsSnapshotAdmin(admin.ModelAdmin):
    list_display = ['snapshot_type', 'period_type', 'academy', 'period_start', 'period_end', 'calculation_version', 'generated_at']
    list_filter = ['snapshot_type', 'period_type', 'calculation_version']
    search_fields = ['snapshot_type', 'academy__name']

@admin.register(ReportJob)
class ReportJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'report_type', 'format', 'status', 'academy', 'requested_by', 'started_at', 'completed_at']
    list_filter = ['report_type', 'format', 'status']
    search_fields = ['report_type', 'requested_by__email', 'academy__name']

@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = ['name', 'report_type', 'academy', 'is_shared', 'created_by', 'created_at']
    list_filter = ['report_type', 'is_shared']
    search_fields = ['name', 'academy__name']
