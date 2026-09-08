from core.models import BaseModel
from django.db import models
from django.utils import timezone
from users_roles.models import User

# --------------------------------------------------------------
# Analytics & Reports Enums
# --------------------------------------------------------------

class SnapshotPeriodType(models.TextChoices):
    DAILY = 'DAILY', 'Daily'
    WEEKLY = 'WEEKLY', 'Weekly'
    MONTHLY = 'MONTHLY', 'Monthly'

class ReportStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'

class ReportFormat(models.TextChoices):
    CSV = 'CSV', 'CSV Spreadsheet'
    XLSX = 'XLSX', 'Excel Spreadsheet'
    PDF = 'PDF', 'PDF Document'

class ReportType(models.TextChoices):
    STUDENTS = 'STUDENTS', 'Student Roster Report'
    ENROLLMENTS = 'ENROLLMENTS', 'Enrollment History Report'
    COURSE_PROGRESS = 'COURSE_PROGRESS', 'Course Learning Progress Report'
    COURSE_COMPLETION = 'COURSE_COMPLETION', 'Course Completion Report'
    PAYMENTS = 'PAYMENTS', 'Payments & Transactions Report'
    COURSE_REVENUE = 'COURSE_REVENUE', 'Course Revenue Report'
    REFUNDS = 'REFUNDS', 'Refunds Report'
    COUPON_USAGE = 'COUPON_USAGE', 'Coupon Usage Report'
    LEADS = 'LEADS', 'Lead Pipeline & Conversion Report'
    LIVE_CLASS_ATTENDANCE = 'LIVE_CLASS_ATTENDANCE', 'Live Session Attendance Report'
    CERTIFICATES = 'CERTIFICATES', 'Issued Certificates Report'
    STORAGE_USAGE = 'STORAGE_USAGE', 'Storage Billing Usage Report'
    CREDIT_USAGE = 'CREDIT_USAGE', 'Credit Consumption Ledger Report'

# --------------------------------------------------------------
# 1. AnalyticsSnapshot Model
# Analytics aggregates domain data but is not the source of truth.
# Payment, Progress, Leads, and Credits domains remain authoritative.
# Historical metrics use persisted snapshots where required for fast trend queries.
# Academy analytics enforce tenant isolation; Platform reports use academy = null.
# Storage history uses immutable usage snapshots, not current files only.
# --------------------------------------------------------------


class AnalyticsSnapshot(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='analytics_snapshots'
    )

    snapshot_type = models.CharField(max_length=100, db_index=True)  # e.g., ACADEMY_OVERVIEW, PLATFORM_OVERVIEW
    period_type = models.CharField(
        max_length=20,
        choices=SnapshotPeriodType.choices,
        default=SnapshotPeriodType.DAILY,
        db_index=True
    )

    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(db_index=True)

    dimensions = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)

    calculation_version = models.CharField(max_length=20, default='v1')
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'analytics_snapshots'
        ordering = ['-period_start']
        indexes = [
            models.Index(fields=['academy', 'snapshot_type', 'period_type']),
            models.Index(fields=['period_start', 'period_end']),
        ]

    def __str__(self):
        return f"Snapshot [{self.snapshot_type}] {self.period_type} - Academy {self.academy_id or 'PLATFORM'}"

# --------------------------------------------------------------
# 2. ReportJob Model
# ReportJob tracks export generation and status for asynchronous tasks.
# Large CSV/XLSX exports run asynchronously through Celery workers.
# Academy analytics enforce tenant isolation; Platform exports use academy = null.
# --------------------------------------------------------------

class ReportJob(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='report_jobs'
    )
    report_type = models.CharField(
        max_length=50,
        choices=ReportType.choices,
        default=ReportType.STUDENTS,
        db_index=True
    )
    format = models.CharField(
        max_length=10,
        choices=ReportFormat.choices,
        default=ReportFormat.CSV
    )

    filters = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ReportStatus.choices,
        default=ReportStatus.PENDING,
        db_index=True
    )
    progress_percent = models.PositiveIntegerField(default=0)

    result_media = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    result_filename = models.CharField(max_length=255, blank=True, default='')

    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='report_jobs'
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'report_jobs'
        ordering = ['-created_at']

    def __str__(self):
        return f"ReportJob {self.id} [{self.report_type}] ({self.status})"

# --------------------------------------------------------------
# 3. SavedReport Model
# SavedReport stores reusable report configuration for tenant staff.
# Stores query parameter filters, not generated binary output files.
# --------------------------------------------------------------


class SavedReport(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='saved_reports'
    )
    name = models.CharField(max_length=255)
    report_type = models.CharField(
        max_length=50,
        choices=ReportType.choices,
        default=ReportType.STUDENTS
    )
    filters = models.JSONField(default=dict, blank=True)
    is_shared = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'saved_reports'
        ordering = ['name']

    def __str__(self):
        return f"SavedReport '{self.name}' ({self.report_type})"
