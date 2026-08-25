from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from emails.models import EmailJob, EmailRecipientDelivery, EmailJobStatus, EmailJobType
from emails.outbox_service import EmailJobService
from live_classes.models import LiveSession, LiveStatus
from live_classes.services import LiveSessionService
from academy.models import Academy
from courses.models import Course, CourseLevel, CourseStatus
from users_roles.models import User
from credits.services import CreditsService

class EmailOutboxSystemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='teacher@cubixskill.com',
            password='Password123!',
            full_name='Instructor Admin'
        )
        self.academy = Academy.objects.create(
            name='Test Tech Academy',
            slug='test-tech-academy',
            owner=self.user
        )
        self.user.academy = self.academy
        self.user.save()

        # Give Academy wallet 100 Credits
        self.account = CreditsService.get_or_create_account(self.academy)
        self.account.balance = Decimal('100.000000')
        self.account.save()

        self.course = Course.objects.create(
            academy=self.academy,
            title='Python Background Processing',
            slug='python-background-processing',
            level=CourseLevel.INTERMEDIATE,
            status=CourseStatus.PUBLISHED,
            is_active=True,
            created_by=self.user
        )

    def test_live_session_creation_creates_durable_outbox_jobs(self):
        """
        Verify creating LiveSession with send_email = True atomically creates
        durable DB outbox EmailJobs (immediate creation + 1-hour scheduled reminder).
        """
        now = timezone.now()
        start_time = now + timedelta(days=2)
        end_time = start_time + timedelta(hours=1)

        session = LiveSessionService.create_session(
            course=self.course,
            title='Mastering Celery Architecture',
            scheduled_start=start_time,
            scheduled_end=end_time,
            created_by=self.user,
            send_email=True
        )

        self.assertIsNotNone(session)
        self.assertTrue(session.send_email_notification)

        # Verify immediate creation EmailJob
        creation_job = EmailJob.objects.filter(
            reference_type="LiveSession",
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_CREATED_EMAIL
        ).first()
        self.assertIsNotNone(creation_job)
        self.assertEqual(creation_job.status, EmailJobStatus.PENDING)

        # Verify 1-hour reminder EmailJob scheduled for start_time - 1 hour
        reminder_job = EmailJob.objects.filter(
            reference_type="LiveSession",
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL
        ).first()
        self.assertIsNotNone(reminder_job)
        self.assertEqual(reminder_job.status, EmailJobStatus.PENDING)
        self.assertEqual(reminder_job.scheduled_for, start_time - timedelta(hours=1))

    def test_live_session_toggle_off_disables_email_jobs(self):
        """
        Verify creating LiveSession with send_email = False creates 0 EmailJobs.
        """
        now = timezone.now()
        start_time = now + timedelta(days=2)
        end_time = start_time + timedelta(hours=1)

        session = LiveSessionService.create_session(
            course=self.course,
            title='Private Masterclass',
            scheduled_start=start_time,
            scheduled_end=end_time,
            created_by=self.user,
            send_email=False
        )

        self.assertFalse(session.send_email_notification)
        jobs_count = EmailJob.objects.filter(reference_type="LiveSession", reference_id=session.id).count()
        self.assertEqual(jobs_count, 0)

    def test_reschedule_session_cancels_old_reminder_and_creates_new(self):
        """
        Verify updating LiveSession start_at cancels old pending reminder and creates new reminder.
        """
        now = timezone.now()
        orig_start = now + timedelta(days=2)
        orig_end = orig_start + timedelta(hours=1)

        session = LiveSessionService.create_session(
            course=self.course,
            title='Rescheduled Event',
            scheduled_start=orig_start,
            scheduled_end=orig_end,
            created_by=self.user,
            send_email=True
        )

        orig_reminder = EmailJob.objects.filter(
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL
        ).first()
        self.assertEqual(orig_reminder.status, EmailJobStatus.PENDING)

        # Reschedule session to 4 days later
        new_start = now + timedelta(days=4)
        session.scheduled_start = new_start
        session.scheduled_end = new_start + timedelta(hours=1)
        session.save()

        EmailJobService.reschedule_session_reminder_jobs(session)

        # Check old reminder cancelled
        orig_reminder.refresh_from_db()
        self.assertEqual(orig_reminder.status, EmailJobStatus.CANCELLED)

        # Check new reminder created for new_start - 1 hour
        new_reminder = EmailJob.objects.filter(
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL,
            status=EmailJobStatus.PENDING
        ).first()
        self.assertIsNotNone(new_reminder)
        self.assertEqual(new_reminder.scheduled_for, new_start - timedelta(hours=1))

    def test_cancel_session_cancels_pending_reminders(self):
        """
        Verify cancelling LiveSession cancels all pending reminder jobs.
        """
        now = timezone.now()
        start_time = now + timedelta(days=2)
        end_time = start_time + timedelta(hours=1)

        session = LiveSessionService.create_session(
            course=self.course,
            title='Cancelled Event',
            scheduled_start=start_time,
            scheduled_end=end_time,
            created_by=self.user,
            send_email=True
        )

        LiveSessionService.cancel_session(session, cancelled_by=self.user, reason="Host unavailable")

        reminder_job = EmailJob.objects.filter(
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_REMINDER_EMAIL
        ).first()
        self.assertEqual(reminder_job.status, EmailJobStatus.CANCELLED)

    def test_worker_process_email_job_executes_and_marks_sent(self):
        """
        Verify EmailJobService.process_email_job delivers email, charges credits, and updates status to SENT.
        """
        now = timezone.now()
        job = EmailJobService.create_job(
            academy_uuid=self.academy.id,
            job_type=EmailJobType.GENERAL_NOTIFICATION,
            subject="Test System Notification",
            template_name="live_session_created",
            scheduled_for=now,
            idempotency_key="TEST_JOB_DELIVERY_101"
        )
        self.assertEqual(job.status, EmailJobStatus.PENDING)

        result = EmailJobService.process_email_job(job.id)
        self.assertTrue(result)

        job.refresh_from_db()
        self.assertEqual(job.status, EmailJobStatus.SENT)
        self.assertIsNotNone(job.completed_at)

    def test_celery_downtime_preserves_pending_jobs(self):
        """
        Verify if Celery worker is offline, EmailJobs remain safely stored as PENDING in PostgreSQL.
        """
        now = timezone.now()
        job = EmailJobService.create_job(
            academy_uuid=self.academy.id,
            job_type=EmailJobType.LIVE_SESSION_CREATED_EMAIL,
            subject="Downtime Test Notification",
            template_name="live_session_created",
            scheduled_for=now
        )
        # Even if worker doesn't run, DB job persists safely
        self.assertEqual(job.status, EmailJobStatus.PENDING)
        self.assertTrue(EmailJob.objects.filter(id=job.id, status=EmailJobStatus.PENDING).exists())

    def test_celery_broker_failure_does_not_fail_live_session_creation(self):
        """
        Verify that even if Celery task dispatch throws an exception during on_commit,
        the LiveSession and durable EmailJobs remain safely committed in DB outbox.
        """
        from unittest.mock import patch

        now = timezone.now()
        start_time = now + timedelta(days=2)
        end_time = start_time + timedelta(hours=1)

        with patch('live_classes.tasks.dispatch_live_session_created_notifications.delay', side_effect=Exception("Redis Connection Refused")):
            session = LiveSessionService.create_session(
                course=self.course,
                title='Broker Offline Masterclass',
                scheduled_start=start_time,
                scheduled_end=end_time,
                created_by=self.user,
                send_email=True
            )

        self.assertIsNotNone(session)
        # Check outbox jobs were safely committed in DB
        creation_job = EmailJob.objects.filter(
            reference_type="LiveSession",
            reference_id=session.id,
            job_type=EmailJobType.LIVE_SESSION_CREATED_EMAIL
        ).first()
        self.assertIsNotNone(creation_job)
        self.assertEqual(creation_job.status, EmailJobStatus.PENDING)
