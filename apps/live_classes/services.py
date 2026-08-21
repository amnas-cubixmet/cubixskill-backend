import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from rest_framework.exceptions import ValidationError

from users_roles.models import User
from enrollments.models import Enrollment, EnrollmentStatus
from notifications.models import Notification, NotificationType
from notifications.services import NotificationService
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveSessionParticipant,
    LiveSessionAttendance,
    LiveSessionEvent,
    LiveStatus,
    ReminderStatus
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# 1. Live Session Email Service
# --------------------------------------------------------------

class LiveSessionEmailService:

    @classmethod
    def send_session_scheduled_emails(cls, session: LiveSession, students: list) -> int:
        from emails.services import send_transactional_email

        course = session.course
        academy = course.academy if course else None
        academy_name = academy.name if academy else "CubixSkill Academy"
        support_email = getattr(academy, 'support_email', None) or getattr(settings, 'SUPPORT_EMAIL', 'support@cubixskill.com')
        tz_str = getattr(academy, 'timezone', 'UTC') if academy else 'UTC'

        start_dt = session.scheduled_start
        date_str = start_dt.strftime("%B %d, %Y")
        time_str = start_dt.strftime("%I:%M %p")

        end_dt = session.scheduled_end
        duration_minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
        duration_str = f"{duration_minutes} minutes"

        join_url = session.meeting_url or f"https://cubixskill.com/courses/{course.id if course else ''}/live-sessions"
        subject = f"Live Session Scheduled: {session.title} – {academy_name}"

        sent_count = 0
        for student in students:
            if not student.email:
                continue

            idempotency_key = f"email_scheduled_{session.id}_{student.id}"
            event_exists = LiveSessionEvent.objects.filter(
                session=session,
                event_type='EMAIL_SENT',
                payload__idempotency_key=idempotency_key
            ).exists()
            if event_exists:
                continue

            context = {
                "student_name": student.full_name or student.email.split('@')[0],
                "academy_name": academy_name,
                "course_title": course.title if course else "Course",
                "session_title": session.title,
                "session_description": session.description,
                "session_date": date_str,
                "session_time": time_str,
                "timezone": tz_str,
                "duration": duration_str,
                "live_session_url": join_url,
                "academy_support_email": support_email,
            }

            try:
                success = send_transactional_email(
                    recipient=student.email,
                    template_name="live_session_scheduled",
                    subject=subject,
                    context=context
                )
                if success:
                    sent_count += 1
                    LiveSessionEvent.objects.create(
                        session=session,
                        event_type='EMAIL_SENT',
                        payload={'type': 'SCHEDULED', 'recipient': student.email, 'idempotency_key': idempotency_key}
                    )
            except Exception as e:
                logger.error(f"Failed to send scheduled email to {student.email}: {e}")

        return sent_count

    @classmethod
    def send_session_reminder_emails(cls, session: LiveSession, students: list) -> int:
        from emails.services import send_transactional_email

        course = session.course
        academy = course.academy if course else None
        academy_name = academy.name if academy else "CubixSkill Academy"
        support_email = getattr(academy, 'support_email', None) or getattr(settings, 'SUPPORT_EMAIL', 'support@cubixskill.com')
        tz_str = getattr(academy, 'timezone', 'UTC') if academy else 'UTC'

        start_dt = session.scheduled_start
        time_str = start_dt.strftime("%I:%M %p")

        end_dt = session.scheduled_end
        duration_minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
        duration_str = f"{duration_minutes} minutes"

        join_url = session.meeting_url or f"https://cubixskill.com/courses/{course.id if course else ''}/live-sessions"
        subject = f"Reminder: {session.title} starts in 1 hour"

        sent_count = 0
        for student in students:
            if not student.email:
                continue

            idempotency_key = f"email_reminder_{session.id}_{student.id}"
            event_exists = LiveSessionEvent.objects.filter(
                session=session,
                event_type='EMAIL_SENT',
                payload__idempotency_key=idempotency_key
            ).exists()
            if event_exists:
                continue

            context = {
                "student_name": student.full_name or student.email.split('@')[0],
                "academy_name": academy_name,
                "course_title": course.title if course else "Course",
                "session_title": session.title,
                "session_time": time_str,
                "timezone": tz_str,
                "duration": duration_str,
                "live_session_url": join_url,
                "academy_support_email": support_email,
            }

            try:
                success = send_transactional_email(
                    recipient=student.email,
                    template_name="live_session_reminder",
                    subject=subject,
                    context=context
                )
                if success:
                    sent_count += 1
                    LiveSessionEvent.objects.create(
                        session=session,
                        event_type='EMAIL_SENT',
                        payload={'type': 'REMINDER', 'recipient': student.email, 'idempotency_key': idempotency_key}
                    )
            except Exception as e:
                logger.error(f"Failed to send reminder email to {student.email}: {e}")

        return sent_count

# --------------------------------------------------------------
# 2. Live Session Notification Service
# --------------------------------------------------------------

class LiveSessionNotificationService:

    @classmethod
    def get_enrolled_students(cls, course) -> list[User]:
        if not course:
            return []
        return list(User.objects.filter(
            enrollments__course=course,
            enrollments__status=EnrollmentStatus.ACTIVE
        ).distinct())

    @classmethod
    def notify_session_created(cls, session: LiveSession, send_email: bool = False) -> tuple[int, int]:
        if not session.course:
            return 0, 0

        students = cls.get_enrolled_students(session.course)
        if not students:
            return 0, 0

        academy = session.course.academy if session.course else None

        # 1. Bulk create In-App Notifications for ALL enrolled students
        date_str = session.scheduled_start.strftime("%b %d, %Y")
        time_str = session.scheduled_start.strftime("%I:%M %p")
        title_text = "New Live Session Scheduled"
        msg_text = f"'{session.title}' has been scheduled for {date_str} at {time_str}. Course: {session.course.title}"

        notifications_to_create = [
            Notification(
                recipient=student,
                notification_type=NotificationType.LIVE_SESSION_CREATED,
                title=title_text,
                message=msg_text,
                action_type="LINK",
                action_url=f"/courses/{session.course.id}/live-sessions",
                source_type="LIVE_SESSION",
                source_id=str(session.id),
                academy=academy
            )
            for student in students
        ]

        in_app_count = 0
        try:
            created_objs = Notification.objects.bulk_create(notifications_to_create, ignore_conflicts=True)
            in_app_count = len(created_objs) if created_objs else len(notifications_to_create)
        except Exception as e:
            logger.error(f"Bulk notification creation failed for session {session.id}: {e}")

        # 2. Immediate Email — ONLY if send_email toggle is True
        emails_sent = 0
        if send_email:
            emails_sent = LiveSessionEmailService.send_session_scheduled_emails(session, students)

        return in_app_count, emails_sent

    @classmethod
    def notify_starting_soon(cls, session: LiveSession, send_email: bool = False) -> tuple[int, int]:
        if not session.course:
            return 0, 0

        students = cls.get_enrolled_students(session.course)
        if not students:
            return 0, 0

        academy = session.course.academy if session.course else None
        time_str = session.scheduled_start.strftime("%I:%M %p")

        # 1. Bulk create In-App Reminders
        notifications_to_create = [
            Notification(
                recipient=student,
                notification_type=NotificationType.LIVE_SESSION_STARTING_SOON,
                title="Live Session Starts in 1 Hour",
                message=f"'{session.title}' starts in 1 hour at {time_str}. Tap to view the session.",
                action_type="LINK",
                action_url=f"/courses/{session.course.id}/live-sessions",
                source_type="LIVE_SESSION",
                source_id=str(session.id),
                academy=academy
            )
            for student in students
        ]

        in_app_count = 0
        try:
            created_objs = Notification.objects.bulk_create(notifications_to_create, ignore_conflicts=True)
            in_app_count = len(created_objs) if created_objs else len(notifications_to_create)
        except Exception as e:
            logger.error(f"Bulk reminder creation failed for session {session.id}: {e}")

        # 2. Reminder Email — ONLY if send_email is True
        emails_sent = 0
        if send_email:
            emails_sent = LiveSessionEmailService.send_session_reminder_emails(session, students)

        return in_app_count, emails_sent

    @classmethod
    def notify_session_started(cls, session: LiveSession) -> int:
        if not session.course:
            return 0

        students = cls.get_enrolled_students(session.course)
        if not students:
            return 0

        academy = session.course.academy if session.course else None

        notifications_to_create = [
            Notification(
                recipient=student,
                notification_type=NotificationType.LIVE_SESSION_CREATED,
                title="Live Session Started",
                message=f"'{session.title}' is now live. Tap to join.",
                action_type="LINK",
                action_url=f"/courses/{session.course.id}/live-sessions",
                source_type="LIVE_SESSION",
                source_id=str(session.id),
                academy=academy
            )
            for student in students
        ]

        in_app_count = 0
        try:
            created_objs = Notification.objects.bulk_create(notifications_to_create, ignore_conflicts=True)
            in_app_count = len(created_objs) if created_objs else len(notifications_to_create)
        except Exception as e:
            logger.error(f"Bulk live-started notification creation failed for session {session.id}: {e}")

        return in_app_count

# --------------------------------------------------------------
# 3. Primary Live Session Service
# --------------------------------------------------------------

class LiveSessionService:

    @classmethod
    @transaction.atomic
    def create_session(
        cls,
        course,
        title: str,
        scheduled_start,
        scheduled_end,
        created_by=None,
        host=None,
        description: str = '',
        session_mode: str = 'EXTERNAL',
        provider: str = 'GOOGLE_MEET',
        meeting_url: str = '',
        max_participants: int = 100,
        recording_enabled: bool = False,
        send_email: bool = False,
        reminders_minutes_before: list[int] = None,
        announce_on_create: bool = False,
        status: str = 'SCHEDULED'
    ) -> LiveSession:
        """
        Creates a new live session with validation, in-app notifications, optional emails, and 1-hour reminders.
        Responds immediately and delegates notification/email dispatch to background processing.
        """
        now = timezone.now()

        # 1. Validation
        if scheduled_end <= scheduled_start:
            raise ValidationError({"scheduled_end": "Scheduled end time must be after scheduled start time."})

        if status != LiveStatus.DRAFT and scheduled_start < now - timedelta(minutes=15):
            raise ValidationError({"scheduled_start": "Scheduled start time cannot be in the past."})

        # 2. Create LiveSession DB Record
        session = LiveSession.objects.create(
            course=course,
            title=title,
            description=description,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status=status,
            session_mode=session_mode,
            provider=provider,
            meeting_url=meeting_url,
            max_participants=max_participants,
            recording_enabled=recording_enabled,
            host=host or created_by,
            created_by=created_by
        )

        # 3. Create Event Log
        LiveSessionEvent.objects.create(
            session=session,
            event_type='SESSION_CREATED',
            payload={'title': title, 'scheduled_start': str(scheduled_start), 'send_email': send_email}
        )

        # 4. Schedule 1-Hour Reminder Record
        reminder_at = scheduled_start - timedelta(hours=1)
        rem_status = ReminderStatus.PENDING if reminder_at > now else ReminderStatus.QUEUED

        idempotency_key = f"rem_{session.id}_60_{int(session.scheduled_start.timestamp())}"
        LiveSessionReminder.objects.get_or_create(
            session=session,
            minutes_before=60,
            defaults={
                'scheduled_for': reminder_at,
                'send_email': send_email,
                'status': rem_status,
                'created_by': created_by,
                'idempotency_key': idempotency_key
            }
        )

        # 5. Dispatch Immediate In-App Notifications & Optional Immediate Email Asynchronously
        if status == LiveStatus.SCHEDULED:
            session_id = str(session.id)

            def queue_notifications():
                try:
                    from live_classes.tasks import dispatch_live_session_created_notifications
                    dispatch_live_session_created_notifications.delay(session_id, send_email=send_email)
                except Exception as e:
                    logger.warning(f"Celery task dispatch failed, executing background thread fallback: {e}")
                    import threading
                    threading.Thread(
                        target=LiveSessionNotificationService.notify_session_created,
                        args=(session, send_email),
                        daemon=True
                    ).start()

            transaction.on_commit(queue_notifications)

        return session

    @classmethod
    def configure_session_reminders(cls, session: LiveSession, minutes_list: list[int], created_by=None, send_email: bool = False):
        now = timezone.now()
        for mins in minutes_list:
            scheduled_for = session.scheduled_start - timedelta(minutes=mins)
            rem_status = ReminderStatus.PENDING if scheduled_for > now else ReminderStatus.QUEUED

            idempotency_key = f"rem_{session.id}_{mins}_{int(session.scheduled_start.timestamp())}"

            LiveSessionReminder.objects.get_or_create(
                session=session,
                minutes_before=mins,
                defaults={
                    'scheduled_for': scheduled_for,
                    'send_email': send_email,
                    'status': rem_status,
                    'created_by': created_by,
                    'idempotency_key': idempotency_key
                }
            )

    @classmethod
    @transaction.atomic
    def update_session(cls, session: LiveSession, send_email: bool = False, **updated_fields) -> LiveSession:
        old_start = session.scheduled_start
        old_end = session.scheduled_end

        new_start = updated_fields.get('scheduled_start', old_start)
        new_end = updated_fields.get('scheduled_end', old_end)

        if new_end <= new_start:
            raise ValidationError({"scheduled_end": "Scheduled end time must be after scheduled start time."})

        # Update attributes
        for field, value in updated_fields.items():
            setattr(session, field, value)

        session.save()

        # Recalculate reminders if start or end changed
        if new_start != old_start or new_end != old_end:
            cls.recalculate_session_reminders(session, send_email=send_email)
            LiveSessionEvent.objects.create(
                session=session,
                event_type='SESSION_RESCHEDULED',
                payload={'new_start': str(new_start), 'new_end': str(new_end)}
            )

        return session

    @classmethod
    @transaction.atomic
    def start_session(cls, session: LiveSession, host_user=None) -> LiveSession:
        logger.info(f"Starting live session {session.id}")
        now = timezone.now()

        # Idempotency safeguard: if already LIVE, return immediately without duplicate processing
        if session.status == LiveStatus.LIVE:
            logger.info(f"Live session {session.id} is already LIVE, returning existing session.")
            return session

        effective = session.calculate_effective_status(now)
        if effective == LiveStatus.ENDED:
            raise ValidationError("Cannot start a session that has already ended.")
        if effective == LiveStatus.CANCELLED:
            raise ValidationError("Cannot start a cancelled session.")

        session.status = LiveStatus.LIVE
        if not session.actual_started_at:
            session.actual_started_at = now
        session.save(update_fields=['status', 'actual_started_at'])

        logger.info(f"Live session {session.id} marked LIVE")

        # Cancel pending reminders so stale "starts in 1 hour" reminders do not fire after starting
        LiveSessionReminder.objects.filter(
            session=session,
            status=ReminderStatus.PENDING
        ).update(status=ReminderStatus.CANCELLED)

        LiveSessionEvent.objects.create(
            session=session,
            event_type='SESSION_STARTED',
            payload={'actual_started_at': str(now)}
        )

        session_id = str(session.id)
        def queue_start_notifications():
            try:
                from live_classes.tasks import dispatch_live_session_started_notifications
                dispatch_live_session_started_notifications.delay(session_id)
                logger.info(f"Queued started notifications for {session_id}")
            except Exception as e:
                logger.warning(f"Could not enqueue Celery start notification task, running thread fallback: {e}")
                import threading
                threading.Thread(
                    target=LiveSessionNotificationService.notify_session_started,
                    args=(session,),
                    daemon=True
                ).start()

        transaction.on_commit(queue_start_notifications)

        return session

    @classmethod
    @transaction.atomic
    def end_session(cls, session: LiveSession, ended_by=None, reason: str = "") -> LiveSession:
        now = timezone.now()
        if session.status == LiveStatus.ENDED and session.actual_ended_at is not None:
            return session

        session.status = LiveStatus.ENDED
        session.actual_ended_at = now
        session.is_recording_active = False
        session.save(update_fields=['status', 'actual_ended_at', 'is_recording_active'])

        # 1. Finalize attendance
        cls.finalize_attendance_for_session(session)

        # 2. Cancel pending reminders
        LiveSessionReminder.objects.filter(
            session=session,
            status=ReminderStatus.PENDING
        ).update(status=ReminderStatus.CANCELLED)

        # 3. Create Event
        LiveSessionEvent.objects.create(
            session=session,
            event_type='SESSION_ENDED',
            payload={
                'actual_ended_at': str(now),
                'ended_by': str(ended_by.id) if ended_by else None,
                'reason': reason
            }
        )

        return session

    @classmethod
    @transaction.atomic
    def cancel_session(cls, session: LiveSession, cancelled_by=None, reason: str = "") -> LiveSession:
        if session.status == LiveStatus.CANCELLED:
            return session

        session.status = LiveStatus.CANCELLED
        session.save(update_fields=['status'])

        # Cancel pending reminders
        LiveSessionReminder.objects.filter(
            session=session,
            status=ReminderStatus.PENDING
        ).update(status=ReminderStatus.CANCELLED)

        # Event & Announcement
        LiveSessionEvent.objects.create(
            session=session,
            event_type='SESSION_CANCELLED',
            payload={'reason': reason}
        )

        cls.dispatch_cancellation_announcement(session, reason=reason)

        return session

    @classmethod
    @transaction.atomic
    def join_session(cls, session: LiveSession, user, role: str = 'ATTENDEE') -> tuple[LiveSessionParticipant, LiveSessionAttendance, dict]:
        now = timezone.now()

        effective = session.calculate_effective_status(now)
        if effective != LiveStatus.LIVE and not (user == session.host or getattr(user, 'is_staff', False)):
            if effective == LiveStatus.ENDED or now > session.scheduled_end or session.actual_ended_at is not None:
                raise ValidationError("This live session has ended and is no longer joinable.")
            if effective == LiveStatus.CANCELLED:
                raise ValidationError("This live session has been cancelled.")
            if effective == LiveStatus.SCHEDULED:
                raise ValidationError("This live session has not started yet.")

        if now > session.scheduled_end or session.actual_ended_at is not None:
            raise ValidationError("This live session has ended and is no longer joinable.")

        if not (user == session.host or getattr(user, 'is_staff', False)):
            if session.course:
                is_enrolled = Enrollment.objects.filter(
                    student=user,
                    course=session.course,
                    status=EnrollmentStatus.ACTIVE
                ).exists()
                if not is_enrolled:
                    raise ValidationError("You must be actively enrolled in the course to join this live session.")

        participant, _ = LiveSessionParticipant.objects.get_or_create(
            session=session,
            user=user,
            defaults={'role': role}
        )

        attendance = LiveSessionAttendance.objects.create(
            participant=participant,
            joined_at=now
        )

        join_info = {
            'session_id': str(session.id),
            'session_mode': session.session_mode,
            'provider': session.provider,
            'meeting_url': session.meeting_url,
            'native_room_id': session.native_room_id,
            'joined_at': attendance.joined_at,
        }

        return participant, attendance, join_info

    @classmethod
    @transaction.atomic
    def leave_session(cls, session: LiveSession, user) -> LiveSessionAttendance | None:
        now = timezone.now()
        attendance = LiveSessionAttendance.objects.filter(
            participant__session=session,
            participant__user=user,
            left_at__isnull=True
        ).order_by('-joined_at').first()

        if attendance:
            attendance.left_at = now
            attendance.duration_seconds = max(0, int((now - attendance.joined_at).total_seconds()))
            attendance.save(update_fields=['left_at', 'duration_seconds'])

        return attendance

    @classmethod
    def finalize_attendance_for_session(cls, session: LiveSession):
        effective_end = session.actual_ended_at or session.scheduled_end or timezone.now()
        open_attendances = LiveSessionAttendance.objects.filter(
            participant__session=session,
            left_at__isnull=True
        )

        for att in open_attendances:
            att.left_at = effective_end
            att.duration_seconds = max(0, int((effective_end - att.joined_at).total_seconds()))
            att.save(update_fields=['left_at', 'duration_seconds'])

    @classmethod
    def recalculate_session_reminders(cls, session: LiveSession, send_email: bool = False):
        now = timezone.now()
        pending_reminders = LiveSessionReminder.objects.filter(
            session=session,
            status=ReminderStatus.PENDING
        )

        for rem in pending_reminders:
            new_scheduled_for = session.scheduled_start - timedelta(minutes=rem.minutes_before)
            rem.scheduled_for = new_scheduled_for
            rem.send_email = send_email
            if new_scheduled_for <= now:
                rem.status = ReminderStatus.QUEUED
            rem.save(update_fields=['scheduled_for', 'status', 'send_email'])

    @classmethod
    def dispatch_cancellation_announcement(cls, session: LiveSession, reason: str = ""):
        if not session.course:
            return

        students = LiveSessionNotificationService.get_enrolled_students(session.course)
        academy = session.course.academy if session.course else None

        for student in students:
            try:
                NotificationService.notify_user(
                    recipient=student,
                    notification_type=NotificationType.LIVE_SESSION_CANCELLED,
                    title="Live Session Cancelled",
                    message=f"The Live Session '{session.title}' has been cancelled. Reason: {reason or 'N/A'}",
                    action_type="LINK",
                    action_url=f"/courses/{session.course.id}/live-sessions",
                    source_type="LIVE_SESSION",
                    source_id=str(session.id),
                    academy=academy
                )
            except Exception as e:
                logger.error(f"Error notifying cancellation for {student.id}: {e}")
