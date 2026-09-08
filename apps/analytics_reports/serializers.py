from analytics_reports.models import (
    AnalyticsSnapshot,
    ReportFormat,
    ReportJob,
    ReportType,
    SavedReport,
)
from rest_framework import serializers

# --------------------------------------------------------------
# Analytics & Reports Serializers
# Serializes precomputed AnalyticsSnapshot trends, asynchronous ReportJob
# statuses, export generation requests, and SavedReport configurations.
# ReportJob tracks export generation status for heavy Celery worker tasks.
# SavedReport stores reusable report configuration for tenant staff.
# --------------------------------------------------------------



class AnalyticsSnapshotSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)

    class Meta:
        model = AnalyticsSnapshot
        fields = [
            'id',
            'academy_id',
            'snapshot_type',
            'period_type',
            'period_start',
            'period_end',
            'dimensions',
            'metrics',
            'calculation_version',
            'generated_at',
        ]
        read_only_fields = fields

class ReportJobSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)
    requested_by_email = serializers.EmailField(source='requested_by.email', read_only=True)

    class Meta:
        model = ReportJob
        fields = [
            'id',
            'academy_id',
            'report_type',
            'format',
            'filters',
            'status',
            'progress_percent',
            'result_filename',
            'requested_by_email',
            'started_at',
            'completed_at',
            'expires_at',
            'error_message',
            'created_at',
        ]
        read_only_fields = fields

class CreateReportJobRequestSerializer(serializers.Serializer):
    report_type = serializers.ChoiceField(choices=ReportType.choices)
    format = serializers.ChoiceField(choices=ReportFormat.choices, default=ReportFormat.CSV)
    filters = serializers.JSONField(required=False, default=dict)

class SavedReportSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)

    class Meta:
        model = SavedReport
        fields = [
            'id',
            'academy_id',
            'name',
            'report_type',
            'filters',
            'is_shared',
            'created_at',
        ]
        read_only_fields = ['id', 'academy_id', 'created_at']
