from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from enrollments.models import Enrollment, EnrollmentStatus
from notifications.services import EmailService
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveSessionParticipant,
    LiveSessionAttendance,
    LiveSessionEvent,
    LiveStatus,
    ReminderStatus
)

# --------------------------------------------------------------
# 1. Live Session Service
# Django manages authorization/session state; media transport is handled by the WebRTC/SFU layer.
# Join access is rejected after scheduled_end even if a background status synchronization task has not run yet.
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
        reminders_minutes_before: list[int] = None,
        announce_on_create: bool = False,
        status: str = 'SCHEDULED'
    ) -> LiveSession:
        """
        Creates a new live session with validation, default/custom reminders, and optional announcement.
        """
        now = timezone.now()

        # 1. Validation
        if scheduled_end <= scheduled_start:
            raise ValidationError({"scheduled_end": "Scheduled end time must be after scheduled start time."})

        if status != LiveStatus.DRAFT and scheduled_start < now - timedelta(minutes=15):
            raise ValidationError({"scheduled_start": "Scheduled start time cannot be in the past."})

        # 2. Create LiveSession
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
            payload={'title': title, 'scheduled_start': str(scheduled_start)}
        )

        # 4. Schedule Reminders
        if reminders_minutes_before is None:
            reminders_minutes_before = [60]  # Default 1-hour reminder

        cls.configure_session_reminders(session, reminders_minutes_before, created_by=created_by)

        # 5. Announcement on creation if enabled
        if announce_on_create and status == LiveStatus.SCHEDULED:
            cls.dispatch_creation_announcement(session)

        return session

    @classmethod
    def configure_session_reminders(cls, session: LiveSession, minutes_list: list[int], created_by=None):
        """
        Configures reminder records for a session based on minutes before start.
        """
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
                    'status': rem_status,
                    'created_by': created_by,
                    'idempotency_key': idempotency_key
                }
            )

    @classmethod
    @transaction.atomic
    def update_session(cls, session: LiveSession, **updated_fields) -> LiveSession:
        """
        Updates a live session. Recalculates reminders if scheduled times change.
        """
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
            cls.recalculate_session_reminders(session)
            LiveSessionEvent.objects.create(
                session=session,
                event_type='SESSION_RESCHEDULED',
                payload={'new_start': str(new_start), 'new_end': str(new_end)}
            )
            cls.dispatch_rescheduled_announcement(session)

        return session

    @classmethod
    @transaction.atomic
    def start_session(cls, session: LiveSession, host_user=None) -> LiveSession:
        """
        Manually starts a session or records start event.
        """
        now = timezone.now()
        effective = session.calculate_effective_status(now)
        if effective == LiveStatus.ENDED:
            raise ValidationError("Cannot start a session that has already ended.")
        if effective == LiveStatus.CANCELLED:
            raise ValidationError("Cannot start a cancelled session.")

        session.status = LiveStatus.LIVE
        if not session.actual_started_at:
            session.actual_started_at = now
        session.save(update_fields=['status', 'actual_started_at'])

        LiveSessionEvent.objects.create(
            session=session,
            event_type='SESSION_STARTED',
            payload={'actual_started_at': str(now)}
        )

        return session

    @classmethod
    @transaction.atomic
    def end_session(cls, session: LiveSession, ended_by=None, reason: str = "") -> LiveSession:
        """
        Ends a session manually or automatically.
        Finalizes attendance, stops recording, and cancels remaining pending reminders.
        """
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
        """
        Cancels a scheduled or live session.
        Cancels pending reminders and notifies enrolled students.
        """
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
        """
        Joins a student or host to a live session after rigorous security and effective state checks.
        """
        now = timezone.now()

        # 1. Authoritative Effective Status Check (Security Rule #4 & #23)
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

        # 2. Student Enrollment Validation
        if not (user == session.host or getattr(user, 'is_staff', False)):
            if session.course:
                is_enrolled = Enrollment.objects.filter(
                    student=user,
                    course=session.course,
                    status=EnrollmentStatus.ACTIVE
                ).exists()
                if not is_enrolled:
                    raise ValidationError("You must be actively enrolled in the course to join this live session.")

        # 3. Create or Get Participant
        participant, _ = LiveSessionParticipant.objects.get_or_create(
            session=session,
            user=user,
            defaults={'role': role}
        )

        # 4. Create Attendance Record
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
        """
        Records a user leaving a session and calculates attendance duration.
        """
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
        """
        Closes all unclosed participant join intervals using actual or scheduled end time.
        """
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
    def recalculate_session_reminders(cls, session: LiveSession):
        """
        Recalculates scheduled_for dates for pending reminders when session start changes.
        """
        now = timezone.now()
        pending_reminders = LiveSessionReminder.objects.filter(
            session=session,
            status=ReminderStatus.PENDING
        )

        for rem in pending_reminders:
            new_scheduled_for = session.scheduled_start - timedelta(minutes=rem.minutes_before)
            rem.scheduled_for = new_scheduled_for
            if new_scheduled_for <= now:
                rem.status = ReminderStatus.QUEUED
            rem.save(update_fields=['scheduled_for', 'status'])

    @classmethod
    def get_enrolled_student_emails(cls, course) -> list[str]:
        if not course:
            return []
        return list(
            Enrollment.objects.filter(
                course=course,
                status=EnrollmentStatus.ACTIVE
            ).select_related('student').values_list('student__email', flat=True)
        )

    @classmethod
    def dispatch_creation_announcement(cls, session: LiveSession):
        recipients = cls.get_enrolled_student_emails(session.course)
        if not recipients:
            return

        subject = f"New Live Class Scheduled: {session.title}"
        context = {
            'body': f"A new Live Class for '{session.course.title if session.course else 'your course'}' has been scheduled for {session.scheduled_start.strftime('%B %d, %Y at %I:%M %p')}.",
            'session_title': session.title,
            'scheduled_start': session.scheduled_start.strftime('%B %d, %Y at %I:%M %p'),
        }

        EmailService.send_bulk(
            recipients=recipients,
            template_code="LIVE_SESSION_CREATED",
            subject=subject,
            context=context,
            academy=session.course.academy if session.course else None
        )

    @classmethod
    def dispatch_rescheduled_announcement(cls, session: LiveSession):
        recipients = cls.get_enrolled_student_emails(session.course)
        if not recipients:
            return

        subject = f"Rescheduled Live Class: {session.title}"
        context = {
            'body': f"The Live Class '{session.title}' has been rescheduled to {session.scheduled_start.strftime('%B %d, %Y at %I:%M %p')}.",
            'session_title': session.title,
            'scheduled_start': session.scheduled_start.strftime('%B %d, %Y at %I:%M %p'),
        }

        EmailService.send_bulk(
            recipients=recipients,
            template_code="LIVE_SESSION_RESCHEDULED",
            subject=subject,
            context=context,
            academy=session.course.academy if session.course else None
        )

    @classmethod
    def dispatch_cancellation_announcement(cls, session: LiveSession, reason: str = ""):
        recipients = cls.get_enrolled_student_emails(session.course)
        if not recipients:
            return

        subject = f"Cancelled Live Class: {session.title}"
        context = {
            'body': f"The Live Class '{session.title}' originally scheduled for {session.scheduled_start.strftime('%B %d, %Y at %I:%M %p')} has been cancelled. Reason: {reason or 'N/A'}.",
            'session_title': session.title,
            'reason': reason,
        }

        EmailService.send_bulk(
            recipients=recipients,
            template_code="LIVE_SESSION_CANCELLED",
            subject=subject,
            context=context,
            academy=session.course.academy if session.course else None
        )
