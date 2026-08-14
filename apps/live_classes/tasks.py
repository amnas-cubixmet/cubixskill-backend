from celery import shared_task
from django.utils import timezone
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveStatus,
    ReminderStatus,
    LiveSessionEvent,
)
from live_classes.services import LiveSessionService

@shared_task
def update_live_session_statuses():
    """
    Periodic task to synchronize database session status with current time.
    Idempotent lifecycle state machine.
    """
    now = timezone.now()
    active_sessions = LiveSession.objects.exclude(
        status__in=[LiveStatus.ENDED, LiveStatus.CANCELLED, LiveStatus.DRAFT]
    )

    updated_count = 0
    for session in active_sessions:
        effective_status = session.calculate_effective_status(now)

        if effective_status == LiveStatus.LIVE and session.status == LiveStatus.SCHEDULED:
            session.status = LiveStatus.LIVE
            if not session.actual_started_at:
                session.actual_started_at = now
            session.save(update_fields=['status', 'actual_started_at'])

            LiveSessionEvent.objects.create(
                session=session,
                event_type='SESSION_STARTED',
                payload={'auto_started_at': str(now)}
            )
            updated_count += 1

        elif effective_status == LiveStatus.ENDED and session.status != LiveStatus.ENDED:
            LiveSessionService.end_session(session, reason="Automatic scheduled_end reached")
            updated_count += 1

    return f"Updated {updated_count} live session statuses at {now}"

@shared_task
def process_pending_live_session_reminders():
    """
    Periodic task to dispatch pending live session reminders.
    """
    now = timezone.now()
    due_reminders = LiveSessionReminder.objects.filter(
        status__in=[ReminderStatus.PENDING, ReminderStatus.QUEUED],
        scheduled_for__lte=now
    ).select_related('session', 'session__course', 'session__course__academy')

    processed_count = 0
    for reminder in due_reminders:
        session = reminder.session
        if not session:
            continue

        effective = session.calculate_effective_status(now)
        if effective in [LiveStatus.ENDED, LiveStatus.CANCELLED]:
            reminder.status = ReminderStatus.CANCELLED
            reminder.save(update_fields=['status'])
            continue

        recipients = LiveSessionService.get_enrolled_student_emails(session.course)
        if recipients:
            subject = f"Reminder: '{session.title}' starts in {reminder.minutes_before} minutes"
            context = {
                'body': f"Your Live Class '{session.title}' is starting in {reminder.minutes_before} minutes at {session.scheduled_start.strftime('%I:%M %p')}.",
                'session_title': session.title,
                'minutes_before': reminder.minutes_before,
                'scheduled_start': session.scheduled_start.strftime('%B %d, %Y at %I:%M %p'),
                'meeting_url': session.meeting_url,
            }
            from notifications.services import EmailService
            EmailService.send_bulk(
                recipients=recipients,
                template_code="LIVE_SESSION_REMINDER",
                subject=subject,
                context=context,
                academy=session.course.academy if session.course else None
            )

        reminder.status = ReminderStatus.SENT
        reminder.sent_at = now
        reminder.save(update_fields=['status', 'sent_at'])
        processed_count += 1

    return f"Processed {processed_count} live session reminders at {now}"
