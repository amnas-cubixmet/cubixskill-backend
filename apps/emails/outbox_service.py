import logging
import math
from decimal import Decimal
from datetime import timedelta
from typing import Optional, List, Dict, Any

from django.db import transaction
from django.utils import timezone

from emails.models import EmailJob, EmailRecipientDelivery, EmailJobStatus, EmailJobType
from emails.services import send_transactional_email

logger = logging.getLogger(__name__)


class EmailJobService:
    @classmethod
    @transaction.atomic
    def create_job(
        cls,
        academy_uuid,
        job_type: str,
        subject: str,
        template_name: str,
        scheduled_for=None,
        reference_type: str = '',
        reference_id=None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> EmailJob:
        """
        Atomically creates a durable EmailJob record in the DB outbox.
        """
        now = timezone.now()
        sched_time = scheduled_for or now

        if idempotency_key:
            existing = EmailJob.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        job = EmailJob.objects.create(
            academy_uuid=academy_uuid,
            job_type=job_type,
            reference_type=reference_type,
            reference_id=reference_id,
            subject=subject,
            template_name=template_name,
            scheduled_for=sched_time,
            status=EmailJobStatus.PENDING,
            idempotency_key=idempotency_key,
            metadata=metadata or {}
        )
        logger.info(f"Created durable EmailJob {job.id} ({job_type}) scheduled for {sched_time}")
        return job

    @classmethod
    @transaction.atomic
    def create_live_session_jobs(cls, session, send_email: bool = True):
        """
        Creates durable outbox EmailJobs for a newly created LiveSession:
        1. Immediate notification email (if send_email is True)
        2. 1-Hour Reminder email (if start_at - 1 hour is in the future)
        """
        if not send_email or not session.send_email_notification:
            logger.info(f"Email notification toggled OFF for LiveSession {session.id}. Skipping creation email job.")
            return

        now = timezone.now()
        academy_id = session.course.academy_id if (session.course and session.course.academy_id) else None

        # 1. Immediate Creation Email Job
        cls.create_job(
            academy_uuid=academy_id,
            job_type=EmailJobType.LIVE_SESSION_CREATED_EMAIL,
            subject=f"New Live Class Scheduled: {session.title}",
            template_name="live_session_created",
            scheduled_for=now,
            reference_type="LiveSession",
            reference_id=session.id,
            idempotency_key=f"LIVE_SESSION_CREATED_{session.id}",
            metadata={
                "session_title": session.title,
                "start_at": str(session.start_at),
                "meeting_link": session.meeting_link or ''
            }
        )

        # 2. 1-Hour Scheduled Reminder Email Job
        reminder_time = session.start_at - timedelta(hours=1)
        if reminder_time > now:
            cls.create_job(
                academy_uuid=academy_id,
                job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL,
                subject=f"Reminder: Live Class '{session.title}' starts in 1 hour",
                template_name="live_session_reminder_1h",
                scheduled_for=reminder_time,
                reference_type="LiveSession",
                reference_id=session.id,
                idempotency_key=f"LIVE_SESSION_REMINDER_1H_{session.id}",
                metadata={
                    "session_title": session.title,
                    "start_at": str(session.start_at),
                    "meeting_link": session.meeting_link or ''
                }
            )

    @classmethod
    @transaction.atomic
    def cancel_session_reminder_jobs(cls, session):
        """
        Cancels any pending reminder EmailJobs for a LiveSession (e.g. when session is cancelled/deleted).
        """
        cancelled_count = EmailJob.objects.filter(
            reference_type="LiveSession",
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL,
            status__in=[EmailJobStatus.PENDING, EmailJobStatus.QUEUED, EmailJobStatus.RETRY]
        ).update(status=EmailJobStatus.CANCELLED)
        logger.info(f"Cancelled {cancelled_count} pending reminder jobs for LiveSession {session.id}")

    @classmethod
    @transaction.atomic
    def reschedule_session_reminder_jobs(cls, session):
        """
        Cancels old pending reminder jobs and schedules a new 1-hour reminder for the updated start time.
        """
        cls.cancel_session_reminder_jobs(session)

        now = timezone.now()
        reminder_time = session.start_at - timedelta(hours=1)
        if reminder_time > now and session.send_email_notification:
            academy_id = session.course.academy_id if (session.course and session.course.academy_id) else None
            cls.create_job(
                academy_uuid=academy_id,
                job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL,
                subject=f"Reminder: Live Class '{session.title}' starts in 1 hour",
                template_name="live_session_reminder_1h",
                scheduled_for=reminder_time,
                reference_type="LiveSession",
                reference_id=session.id,
                idempotency_key=f"LIVE_SESSION_REMINDER_1H_{session.id}_{int(session.start_at.timestamp())}",
                metadata={
                    "session_title": session.title,
                    "start_at": str(session.start_at),
                    "meeting_link": session.meeting_link or ''
                }
            )

    @classmethod
    def process_email_job(cls, job_id: str) -> bool:
        """
        Worker delivery engine:
        1. Row locks the EmailJob record to prevent duplicate worker execution.
        2. Validates job status and reference domain object.
        3. Dynamically resolves active eligible recipients at send time.
        4. Calculates and charges Email Credit cost via CreditService.
        5. Dispatches email batches via EmailService.
        6. Updates EmailJob and recipient delivery records.
        """
        with transaction.atomic():
            job = EmailJob.objects.select_for_update().filter(id=job_id).first()
            if not job:
                logger.warning(f"EmailJob {job_id} not found.")
                return False

            if job.status == EmailJobStatus.SENT:
                logger.info(f"EmailJob {job_id} is already SENT. Skipping.")
                return True

            if job.status == EmailJobStatus.CANCELLED:
                logger.info(f"EmailJob {job_id} is CANCELLED. Skipping.")
                return True

            # Mark PROCESSING
            job.status = EmailJobStatus.PROCESSING
            job.started_at = timezone.now()
            job.attempt_count += 1
            job.save(update_fields=['status', 'started_at', 'attempt_count'])

        # Resolve Domain Reference & Recipient Emails
        recipients = cls._resolve_job_recipients(job)
        if not recipients:
            logger.info(f"EmailJob {job.id} has 0 eligible recipients. Marking SENT.")
            job.status = EmailJobStatus.SENT
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'completed_at'])
            return True

        # Email Credit Cost Calculation & Ledger Charge
        if job.academy_uuid:
            from academy.models import Academy
            from credits.services import CreditsService, CreditPricingService
            from credits.models import CreditSourceType

            academy = Academy.objects.filter(id=job.academy_uuid).first()
            if academy:
                rate = CreditPricingService.get_rate('EMAIL_SEND')
                per_email_cost = rate.credit_cost if rate else Decimal('1.0000')
                total_required_credits = per_email_cost * Decimal(str(len(recipients)))

                account = CreditsService.get_or_create_account(academy)
                if account.balance < total_required_credits:
                    logger.warning(f"Academy {academy.id} has insufficient credits for EmailJob {job.id}. Required: {total_required_credits}, Available: {account.balance}")
                    job.status = EmailJobStatus.FAILED
                    job.last_error = f"INSUFFICIENT_CREDITS: Required {total_required_credits}, Available {account.balance}"
                    job.save(update_fields=['status', 'last_error'])
                    return False

                # Debit Credits idempotently via central CreditsService
                try:
                    CreditsService.debit(
                        academy=academy,
                        amount=total_required_credits,
                        source_type=CreditSourceType.EMAIL_USAGE,
                        idempotency_key=f"EMAIL_JOB_DEBIT_{job.id}_ATTEMPT_{job.attempt_count}",
                        description=f"Email dispatch: {job.job_type} ({len(recipients)} recipients)",
                        reference_type='EMAIL_JOB',
                        reference_id=str(job.id)
                    )
                except Exception as e:
                    logger.error(f"Credit debit failed for EmailJob {job.id}: {e}")

        # Send Batch Emails
        sent_count = 0
        failed_count = 0

        for r_user_id, r_email, r_name in recipients:
            context = {
                "user_name": r_name,
                "session_title": job.metadata.get("session_title", ""),
                "start_at": job.metadata.get("start_at", ""),
                "meeting_link": job.metadata.get("meeting_link", ""),
                "subject": job.subject
            }
            success = send_transactional_email(
                recipient=r_email,
                template_name=job.template_name or "live_session_created",
                subject=job.subject,
                context=context
            )

            # Record delivery status
            EmailRecipientDelivery.objects.update_or_create(
                job=job,
                recipient_email=r_email,
                defaults={
                    'recipient_user_uuid': r_user_id,
                    'status': EmailJobStatus.SENT if success else EmailJobStatus.FAILED,
                    'sent_at': timezone.now() if success else None,
                    'error_message': '' if success else 'SMTP delivery failed'
                }
            )

            if success:
                sent_count += 1
            else:
                failed_count += 1

        now = timezone.now()

        if failed_count == 0 or sent_count > 0:
            job.status = EmailJobStatus.SENT
            job.completed_at = now
            job.last_error = f"Sent to {sent_count} recipients successfully." if failed_count == 0 else f"Sent: {sent_count}, Failed: {failed_count}"
            job.save(update_fields=['status', 'completed_at', 'last_error'])
            logger.info(f"EmailJob {job.id} completed. Sent: {sent_count}, Failed: {failed_count}")
            return True
        else:
            # Handle Retry with Exponential Backoff
            if job.attempt_count < job.max_attempts:
                backoff_minutes = int(math.pow(2, job.attempt_count))
                next_retry = now + timedelta(minutes=backoff_minutes)
                job.status = EmailJobStatus.PENDING
                job.next_retry_at = next_retry
                job.last_error = f"Attempt {job.attempt_count} failed. Next retry at {next_retry}"
                job.save(update_fields=['status', 'next_retry_at', 'last_error'])
                logger.warning(f"EmailJob {job.id} failed attempt {job.attempt_count}. Retrying at {next_retry}")
            else:
                job.status = EmailJobStatus.FAILED
                job.completed_at = now
                job.last_error = f"Max attempts ({job.max_attempts}) reached. Delivery failed."
                job.save(update_fields=['status', 'completed_at', 'last_error'])
                logger.error(f"EmailJob {job.id} permanently FAILED after {job.attempt_count} attempts.")
            return False

    @classmethod
    def _resolve_job_recipients(cls, job: EmailJob) -> List[tuple]:
        """
        Dynamically resolves recipient (user_id, email, full_name) tuples for a job at send time.
        """
        if job.reference_type == "LiveSession" and job.reference_id:
            from live_classes.models import LiveSession, LiveStatus
            session = LiveSession.objects.select_related('course').filter(id=job.reference_id).first()
            if not session or session.status in [LiveStatus.CANCELLED, LiveStatus.ENDED]:
                logger.info(f"LiveSession {job.reference_id} is cancelled or ended. No recipients resolved.")
                return []

            # Find enrolled students for the course
            from enrollments.models import Enrollment
            enrollments = Enrollment.objects.filter(
                course=session.course,
                status='ACTIVE'
            ).select_related('student', 'student__user')

            recipients = []
            for enr in enrollments:
                u = enr.student.user if (hasattr(enr.student, 'user') and enr.student.user) else None
                email = getattr(u, 'email', None) or getattr(enr.student, 'email', None)
                name = getattr(u, 'full_name', '') or getattr(enr.student, 'full_name', 'Student')
                if email and '@' in email:
                    recipients.append((u.id if u else None, email, name))

            return recipients

        return []
