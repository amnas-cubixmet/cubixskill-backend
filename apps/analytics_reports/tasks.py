import logging
from celery import shared_task
from django.utils import timezone
from analytics_reports.models import ReportJob, ReportStatus
from analytics_reports.services import ReportService, AnalyticsSnapshotService

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# 1. Asynchronous Report Generation Worker Task
# Large CSV/XLSX exports run asynchronously through Celery.
# ReportJob tracks export generation and status lifecycle.
# --------------------------------------------------------------

@shared_task(bind=True, queue='reports_generation', max_retries=2, default_retry_delay=60)
def generate_report_task(self, job_id: str):
    logger.info(f"Starting report generation task for ReportJob {job_id}")
    try:
        ReportService.generate_report_file(job_id)
    except Exception as exc:
        logger.error(f"Report generation task failed for ReportJob {job_id}: {exc}")
        if self.request.retries >= self.max_retries:
            try:
                job = ReportJob.objects.get(id=job_id)
                job.status = ReportStatus.FAILED
                job.error_message = str(exc)
                job.completed_at = timezone.now()
                job.save(update_fields=['status', 'error_message', 'completed_at'])
            except ReportJob.DoesNotExist:
                pass
        else:
            raise self.retry(exc=exc)

# --------------------------------------------------------------
# 2. Daily Snapshot Aggregation Task (Celery Beat)
# Historical metrics use persisted snapshots where required.
# Aggregates active Academy metrics into AnalyticsSnapshot records daily.
# --------------------------------------------------------------


@shared_task
def generate_daily_analytics_snapshots_task():
    logger.info("Starting daily analytics snapshot aggregation...")
    count = AnalyticsSnapshotService.generate_daily_snapshots()
    return f"Generated daily analytics snapshots for {count} academies."

# --------------------------------------------------------------
# 3. Expired Report Cleanup Task (Celery Beat)
# Marks old report jobs EXPIRED after 24-hour retention window.
# --------------------------------------------------------------

@shared_task
def cleanup_expired_report_jobs_task():
    now = timezone.now()
    expired_jobs = ReportJob.objects.filter(
        status=ReportStatus.COMPLETED,
        expires_at__lte=now
    )
    count = expired_jobs.update(status=ReportStatus.EXPIRED)
    logger.info(f"Marked {count} expired ReportJobs as EXPIRED.")
    return f"Cleaned up {count} expired report jobs."
