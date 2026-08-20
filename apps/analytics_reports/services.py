import csv
import io
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.core.files.base import ContentFile
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User
from storage.models import MediaFile
from notifications.services import NotificationService
from analytics_reports.models import (
    AnalyticsSnapshot,
    ReportJob,
    ReportStatus,
    ReportFormat,
    ReportType,
    SnapshotPeriodType,
)
from analytics_reports.selectors import AnalyticsSelector
from students.models import StudentProfile
from enrollments.models import Enrollment
from courses.models import Course
from payments.models import PaymentOrder
from leads.models import Lead

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Central Analytics & Report Generation Service
# Analytics aggregates domain data but is not the source of truth;
# Payment, Progress, Leads, and Credits domains remain authoritative for data.
# Large CSV/XLSX exports should run asynchronously through Celery.
# ReportJob tracks export generation and status lifecycle.
# Historical metrics use persisted snapshots where required for daily trend queries.
# Academy analytics must enforce tenant isolation; Platform reports use academy = null.
# Storage history must use immutable usage snapshots, not current files only.
# --------------------------------------------------------------


class ReportService:

    @classmethod
    @transaction.atomic
    def create_report_job(
        cls,
        user: User,
        report_type: str,
        format_type: str = ReportFormat.CSV,
        filters: dict = None,
        academy: Academy = None
    ) -> ReportJob:
        """
        Creates ReportJob record and dispatches asynchronous Celery worker task.
        """
        filters = filters or {}
        academy = academy or getattr(user, 'academy', None)

        if report_type not in ReportType.values:
            raise ValidationError({"report_type": f"Unsupported report type '{report_type}'."})

        job = ReportJob.objects.create(
            academy=academy,
            report_type=report_type,
            format=format_type,
            filters=filters,
            status=ReportStatus.PENDING,
            requested_by=user
        )

        from analytics_reports.tasks import generate_report_task
        transaction.on_commit(lambda: generate_report_task.delay(str(job.id)))

        return job

    @classmethod
    def generate_report_file(cls, job_id: str) -> ReportJob:
        """
        Asynchronously fetches report data in memory-safe chunks, renders CSV file,
        attaches MediaFile, updates status to COMPLETED, and notifies requesting user.
        """
        try:
            job = ReportJob.objects.get(id=job_id)
        except ReportJob.DoesNotExist:
            logger.error(f"ReportJob {job_id} not found.")
            return None

        job.status = ReportStatus.PROCESSING
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])

        try:
            output = io.StringIO()
            writer = csv.writer(output)

            # Build report columns and data depending on report_type
            if job.report_type == ReportType.STUDENTS:
                writer.writerow(['Student Code', 'Full Name', 'Email', 'Phone', 'Status', 'Created At'])
                qs = StudentProfile.objects.filter(user__academy=job.academy).select_related('user')
                for s in qs.iterator(chunk_size=500):
                    writer.writerow([s.student_code, s.user.full_name, s.user.email, getattr(s.user, 'phone', ''), s.status, s.created_at.isoformat()])

            elif job.report_type == ReportType.ENROLLMENTS:
                writer.writerow(['Student Name', 'Course Title', 'Access Type', 'Status', 'Enrolled At'])
                qs = Enrollment.objects.filter(student__academy=job.academy).select_related('student', 'course')
                for e in qs.iterator(chunk_size=500):
                    writer.writerow([e.student.full_name, e.course.title, e.access_type, e.status, e.created_at.isoformat()])

            elif job.report_type == ReportType.PAYMENTS:
                writer.writerow(['Order Number', 'Payer Email', 'Context', 'Amount', 'Currency', 'Status', 'Gateway', 'Completed At'])
                qs = PaymentOrder.objects.filter(academy=job.academy).select_related('payer')
                for p in qs.iterator(chunk_size=500):
                    payer_email = p.payer.email if p.payer else ''
                    writer.writerow([p.order_number, payer_email, p.payment_context, str(p.final_amount), p.currency, p.status, p.gateway, p.completed_at.isoformat() if p.completed_at else ''])

            elif job.report_type == ReportType.LEADS:
                writer.writerow(['Lead Name', 'Email', 'Phone', 'Source', 'Status', 'Priority', 'Created At'])
                qs = Lead.objects.filter(academy=job.academy)
                for l in qs.iterator(chunk_size=500):
                    writer.writerow([l.full_name, l.email, l.phone, l.source, l.status, l.priority, l.created_at.isoformat()])

            else:
                writer.writerow(['Report Type', 'Generated At'])
                writer.writerow([job.report_type, timezone.now().isoformat()])

            # Save generated CSV file to MediaFile
            file_name = f"report_{job.report_type.lower()}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
            csv_bytes = output.getvalue().encode('utf-8')
            django_file = ContentFile(csv_bytes, name=file_name)

            media_file = MediaFile.objects.create(
                academy_uuid=job.academy.id if job.academy else None,
                original_filename=file_name,
                stored_filename=file_name,
                storage_key=f"reports/{file_name}",
                relative_path=f"reports/{file_name}",
                size_bytes=len(csv_bytes),
                mime_type='text/csv',
                media_type='DOCUMENT',
                status='ACTIVE',
                uploaded_by_uuid=job.requested_by.id if job.requested_by else None
            )


            now = timezone.now()
            job.status = ReportStatus.COMPLETED
            job.progress_percent = 100
            job.result_media = media_file
            job.result_filename = file_name
            job.completed_at = now
            job.expires_at = now + timedelta(days=1)  # 24-hour expiry
            job.save()

            # Send Notification to user
            if job.requested_by:
                NotificationService.notify_user(
                    recipient=job.requested_by,
                    notification_type="REPORT_READY",
                    title="Export Report Ready",
                    message=f"Your '{job.report_type}' export report is ready for download.",
                    action_type="LINK",
                    action_url=f"/api/v1/reports/{job.id}/download/",
                    source_type="REPORT_JOB",
                    source_id=str(job.id),
                    academy=job.academy
                )

            return job

        except Exception as exc:
            logger.error(f"Failed to generate report job {job_id}: {exc}")
            job.status = ReportStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'completed_at'])
            return job


class AnalyticsSnapshotService:

    @classmethod
    @transaction.atomic
    def generate_daily_snapshots(cls, date=None) -> int:
        """
        Periodic Celery Beat aggregator task generating precomputed daily AnalyticsSnapshots.
        """
        now = date or timezone.now()
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        period_end = period_start + timedelta(days=1)

        count = 0
        for academy in Academy.objects.filter(is_active=True):
            metrics = AnalyticsSelector.get_academy_dashboard(academy, date_from=period_start, date_to=period_end)

            AnalyticsSnapshot.objects.update_or_create(
                academy=academy,
                snapshot_type='ACADEMY_OVERVIEW',
                period_type=SnapshotPeriodType.DAILY,
                period_start=period_start,
                defaults={
                    'period_end': period_end,
                    'metrics': metrics,
                    'calculation_version': 'v1',
                    'generated_at': timezone.now()
                }
            )
            count += 1

        return count
