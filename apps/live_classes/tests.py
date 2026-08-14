from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment, EnrollmentStatus
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveSessionParticipant,
    LiveSessionAttendance,
    LiveSessionEvent,
    LiveStatus,
    ReminderStatus,
)
from live_classes.services import LiveSessionService
from live_classes.selectors import LiveSessionSelector
from live_classes.tasks import update_live_session_statuses, process_pending_live_session_reminders

class LiveClassesTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # 1. Setup Academy, Staff & Student
        self.academy = Academy.objects.create(name="Live Academy", slug="live-academy")
        self.staff = User.objects.create_user(
            email="instructor@test.com",
            password="Password123!",
            full_name="Instructor John",
            academy=self.academy,
            is_staff=True
        )

        self.student = User.objects.create_user(
            email="student@test.com",
            password="Password123!",
            full_name="Student Jane"
        )

        self.unregistered_student = User.objects.create_user(
            email="outsider@test.com",
            password="Password123!",
            full_name="Outsider Bob"
        )

        # 2. Setup Course & Enrollment
        self.course = Course.objects.create(
            academy=self.academy,
            title="Advanced Python Live",
            status=CourseStatus.PUBLISHED
        )

        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            status=EnrollmentStatus.ACTIVE
        )

    def test_session_creation_and_validation(self):
        now = timezone.now()

        # 1. Reject scheduled_end <= scheduled_start
        with self.assertRaises(ValidationError):
            LiveSessionService.create_session(
                course=self.course,
                title="Invalid End Time Session",
                scheduled_start=now + timedelta(hours=2),
                scheduled_end=now + timedelta(hours=1),
                created_by=self.staff
            )

        # 2. Create valid session
        start_time = now + timedelta(hours=2)
        end_time = now + timedelta(hours=3, minutes=30)

        session = LiveSessionService.create_session(
            course=self.course,
            title="Python Concurrency Live",
            scheduled_start=start_time,
            scheduled_end=end_time,
            created_by=self.staff,
            reminders_minutes_before=[60, 15],
            announce_on_create=True
        )

        self.assertEqual(session.status, LiveStatus.SCHEDULED)
        self.assertEqual(session.title, "Python Concurrency Live")

        # Verify reminders created
        reminders = list(session.reminders.all().order_by('minutes_before'))
        self.assertEqual(len(reminders), 2)
        self.assertEqual(reminders[0].minutes_before, 15)
        self.assertEqual(reminders[1].minutes_before, 60)

        # Verify event logged
        event = LiveSessionEvent.objects.filter(session=session, event_type='SESSION_CREATED').first()
        self.assertIsNotNone(event)

    def test_authoritative_effective_status_and_join_security(self):
        now = timezone.now()

        # Create session where scheduled_end has passed but status is still SCHEDULED in DB
        past_start = now - timedelta(hours=3)
        past_end = now - timedelta(hours=1)

        expired_session = LiveSession.objects.create(
            course=self.course,
            title="Stale DB Status Session",
            scheduled_start=past_start,
            scheduled_end=past_end,
            status=LiveStatus.SCHEDULED,
            host=self.staff
        )

        # Effective status MUST evaluate to ENDED
        self.assertEqual(expired_session.calculate_effective_status(now), LiveStatus.ENDED)

        # SECURITY RULE CHECK: Student join attempt MUST be rejected!
        with self.assertRaises(ValidationError):
            LiveSessionService.join_session(expired_session, self.student)

        # Unenrolled student attempt MUST be rejected even if session is live
        live_start = now - timedelta(minutes=10)
        live_end = now + timedelta(minutes=50)

        live_session = LiveSession.objects.create(
            course=self.course,
            title="Active Live Session",
            scheduled_start=live_start,
            scheduled_end=live_end,
            status=LiveStatus.LIVE,
            host=self.staff
        )

        with self.assertRaises(ValidationError):
            LiveSessionService.join_session(live_session, self.unregistered_student)

        # Enrolled student join MUST succeed
        participant, attendance, join_info = LiveSessionService.join_session(live_session, self.student)
        self.assertEqual(participant.user, self.student)
        self.assertIsNotNone(attendance.joined_at)
        self.assertIn('meeting_url', join_info)

    def test_manual_end_session_and_attendance_finalization(self):
        now = timezone.now()

        live_session = LiveSessionService.create_session(
            course=self.course,
            title="Session to End",
            scheduled_start=now - timedelta(minutes=5),
            scheduled_end=now + timedelta(hours=1),
            created_by=self.staff,
            status=LiveStatus.LIVE
        )

        # Student joins
        participant, attendance, _ = LiveSessionService.join_session(live_session, self.student)
        self.assertIsNone(attendance.left_at)

        # Host manually ends session early
        ended_session = LiveSessionService.end_session(live_session, ended_by=self.staff, reason="Host wrapped up early")

        self.assertEqual(ended_session.status, LiveStatus.ENDED)
        self.assertIsNotNone(ended_session.actual_ended_at)

        # Attendance must be finalized automatically
        attendance.refresh_from_db()
        self.assertIsNotNone(attendance.left_at)
        self.assertGreaterEqual(attendance.duration_seconds, 0)

        # Cannot join ended session
        with self.assertRaises(ValidationError):
            LiveSessionService.join_session(ended_session, self.student)

    def test_celery_automatic_status_update_task(self):
        now = timezone.now()

        # 1. Upcoming session that should transition to LIVE
        should_be_live = LiveSession.objects.create(
            course=self.course,
            title="Session Should Be Live",
            scheduled_start=now - timedelta(minutes=5),
            scheduled_end=now + timedelta(minutes=55),
            status=LiveStatus.SCHEDULED,
            host=self.staff
        )

        # 2. Expired session that should transition to ENDED
        should_be_ended = LiveSession.objects.create(
            course=self.course,
            title="Session Should Be Ended",
            scheduled_start=now - timedelta(hours=2),
            scheduled_end=now - timedelta(minutes=10),
            status=LiveStatus.LIVE,
            host=self.staff
        )

        # Execute Celery task
        update_live_session_statuses()

        should_be_live.refresh_from_db()
        should_be_ended.refresh_from_db()

        self.assertEqual(should_be_live.status, LiveStatus.LIVE)
        self.assertEqual(should_be_ended.status, LiveStatus.ENDED)

    def test_pending_reminders_celery_task(self):
        now = timezone.now()
        session = LiveSessionService.create_session(
            course=self.course,
            title="Reminder Test Session",
            scheduled_start=now + timedelta(minutes=50),
            scheduled_end=now + timedelta(hours=2),
            created_by=self.staff,
            reminders_minutes_before=[60]
        )

        reminder = session.reminders.first()
        reminder.scheduled_for = now - timedelta(minutes=1)  # Force due
        reminder.save()

        process_pending_live_session_reminders()

        reminder.refresh_from_db()
        self.assertEqual(reminder.status, ReminderStatus.SENT)
        self.assertIsNotNone(reminder.sent_at)

    def test_reschedule_recalculates_pending_reminders(self):
        now = timezone.now()
        session = LiveSessionService.create_session(
            course=self.course,
            title="Original Schedule",
            scheduled_start=now + timedelta(hours=3),
            scheduled_end=now + timedelta(hours=4),
            created_by=self.staff,
            reminders_minutes_before=[60]
        )

        old_reminder_time = session.reminders.first().scheduled_for

        # Reschedule 2 hours later
        new_start = now + timedelta(hours=5)
        new_end = now + timedelta(hours=6)

        LiveSessionService.update_session(
            session=session,
            scheduled_start=new_start,
            scheduled_end=new_end
        )

        new_reminder_time = session.reminders.first().scheduled_for
        self.assertNotEqual(old_reminder_time, new_reminder_time)
        self.assertEqual(new_reminder_time, new_start - timedelta(minutes=60))

    def test_student_categorized_live_classes_api(self):
        now = timezone.now()

        # 1. Live Now
        LiveSession.objects.create(
            course=self.course,
            title="Live Now Class",
            scheduled_start=now - timedelta(minutes=10),
            scheduled_end=now + timedelta(minutes=50),
            status=LiveStatus.LIVE,
            host=self.staff
        )

        # 2. Upcoming
        LiveSession.objects.create(
            course=self.course,
            title="Upcoming Class",
            scheduled_start=now + timedelta(hours=5),
            scheduled_end=now + timedelta(hours=6),
            status=LiveStatus.SCHEDULED,
            host=self.staff
        )

        # 3. Past
        LiveSession.objects.create(
            course=self.course,
            title="Past Class",
            scheduled_start=now - timedelta(hours=5),
            scheduled_end=now - timedelta(hours=3),
            status=LiveStatus.ENDED,
            host=self.staff
        )

        self.client.force_authenticate(user=self.student)
        url = "/api/v1/student/live-classes/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn('live_now', data)
        self.assertIn('upcoming', data)
        self.assertIn('past', data)

        self.assertEqual(len(data['live_now']), 1)
        self.assertEqual(len(data['upcoming']), 1)
        self.assertEqual(len(data['past']), 1)
        self.assertEqual(data['live_now'][0]['title'], "Live Now Class")
        self.assertEqual(data['upcoming'][0]['title'], "Upcoming Class")
        self.assertEqual(data['past'][0]['title'], "Past Class")
