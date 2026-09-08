import csv
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from leads.models import FollowUpStatus, ImportJobStatus, LeadFollowUp, LeadImportJob
from leads.services import LeadService
from notifications.services import EmailService

# --------------------------------------------------------------
# 1. Lead Follow-Up Reminders Task
# Leads owns follow-up timing and recipient/business context.
# Notifications service owns actual email and in-app delivery.
# --------------------------------------------------------------

@shared_task
def check_lead_follow_up_reminders():
    """
    Periodic Celery Beat task checking for due or overdue Lead follow-ups.
    Sends reminders via centralized EmailService without blocking main thread.
    """
    now = timezone.now()
    due_follow_ups = LeadFollowUp.objects.filter(
        status=FollowUpStatus.PENDING,
        scheduled_at__lte=now + timedelta(minutes=15)
    ).select_related('lead', 'assigned_to', 'lead__academy')

    notified_count = 0
    for follow_up in due_follow_ups:
        recipient_user = follow_up.assigned_to or follow_up.lead.assigned_to
        if recipient_user and recipient_user.email:
            is_overdue = follow_up.scheduled_at < now
            event_title = "OVERDUE Lead Follow-Up" if is_overdue else "Upcoming Lead Follow-Up"

            EmailService.send_transactional(
                recipient=recipient_user.email,
                template_code="LEAD_FOLLOW_UP_REMINDER",
                subject=f"{event_title}: {follow_up.lead.full_name}",
                context={
                    'body': f"Follow-up ({follow_up.follow_up_type}) for lead '{follow_up.lead.full_name}' is scheduled for {follow_up.scheduled_at.strftime('%B %d, %Y at %I:%M %p')}.",
                    'lead_name': follow_up.lead.full_name,
                    'scheduled_at': follow_up.scheduled_at.strftime('%B %d, %Y at %I:%M %p'),
                },
                user=recipient_user,
                academy=follow_up.lead.academy
            )
            notified_count += 1

    return f"Processed {notified_count} follow-up reminders at {now}"

# --------------------------------------------------------------
# 2. Lead Import Processing Task
# Processes large CSV imports asynchronously.
# Import files use centralized MediaFile (local development storage).
# --------------------------------------------------------------

@shared_task
def process_lead_import_job(job_id: str):
    """
    Asynchronous Celery task to import Leads from CSV MediaFile.
    """
    try:
        job = LeadImportJob.objects.get(id=job_id)
    except LeadImportJob.DoesNotExist:
        return f"Import job {job_id} not found."

    job.status = ImportJobStatus.PROCESSING
    job.started_at = timezone.now()
    job.save(update_fields=['status', 'started_at'])

    if not job.source_media_file:
        job.status = ImportJobStatus.FAILED
        job.save(update_fields=['status'])
        return "Source media file missing."

    try:
        # Open local media file
        from django.conf import settings
        file_path = settings.MEDIA_ROOT / job.source_media_file.relative_path

        created_count = 0
        updated_count = 0
        failed_count = 0
        total_rows = 0

        with open(file_path, mode='r', encoding='utf-8-sig') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                total_rows += 1
                name = row.get('name') or row.get('full_name') or row.get('Name') or ''
                email = row.get('email') or row.get('Email') or ''
                phone = row.get('phone') or row.get('Phone') or ''
                source = row.get('source') or 'IMPORT'

                if not name or (not email and not phone):
                    failed_count += 1
                    continue

                try:
                    _, created = LeadService.create_or_update_lead(
                        academy=job.academy,
                        full_name=name,
                        email=email,
                        phone=phone,
                        source=source,
                        created_by=job.uploaded_by
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                except Exception:
                    failed_count += 1

                job.processed_rows = total_rows
                job.save(update_fields=['processed_rows'])

        job.total_rows = total_rows
        job.created_count = created_count
        job.updated_count = updated_count
        job.failed_count = failed_count
        job.status = ImportJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.save()

        return f"Import job {job_id} completed: {created_count} created, {updated_count} updated, {failed_count} failed."

    except Exception as e:
        job.status = ImportJobStatus.FAILED
        job.completed_at = timezone.now()
        job.save()
        return f"Import job failed: {e!s}"
