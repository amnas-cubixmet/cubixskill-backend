import logging
from celery import shared_task
from django.utils import timezone
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveStatus,
    ReminderStatus,
    LiveSessionEvent,
)

logger = logging.getLogger(__name__)

@shared_task(bind=True, queue='default', ignore_result=True, max_retries=3, default_retry_delay=60)
def dispatch_live_session_created_notifications(self, session_id: str, send_email: bool = False):
    """
    Background task to dispatch live session creation in-app notifications.
    Executes asynchronously outside the HTTP request/response cycle.
    """
    try:
        from live_classes.services import LiveSessionNotificationService
        session = LiveSession.objects.select_related('course', 'course__academy').filter(id=session_id).first()
        if not session:
            logger.warning(f"LiveSession {session_id} not found when executing background notification task.")
            return f"Session {session_id} not found."

        in_app_count, emails_sent = LiveSessionNotificationService.notify_session_created(session, send_email=send_email)
        return f"Dispatched {in_app_count} notifications and {emails_sent} emails for session {session_id}"
    except Exception as exc:
        logger.error(f"Error in dispatch_live_session_created_notifications task for session {session_id}: {exc}")
        raise self.retry(exc=exc)

@shared_task(bind=True, queue='default', ignore_result=True, max_retries=3, default_retry_delay=60)
def dispatch_live_session_started_notifications(self, session_id: str):
    """
    Background task to dispatch live session started in-app notifications to enrolled students.
    """
    try:
        from live_classes.services import LiveSessionNotificationService
        session = LiveSession.objects.select_related('course', 'course__academy').filter(id=session_id).first()
        if not session:
            logger.warning(f"LiveSession {session_id} not found when executing background start notification task.")
            return f"Session {session_id} not found."

        in_app_count = LiveSessionNotificationService.notify_session_started(session)
        logger.info(f"Queued started notifications for session {session_id}: {in_app_count} recipients")
        return f"Dispatched {in_app_count} live-started notifications for session {session_id}"
    except Exception as exc:
        logger.exception(f"Failed background start processing for session {session_id}: {exc}")
        raise self.retry(exc=exc)

@shared_task(queue='default', ignore_result=True)
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
            from live_classes.services import LiveSessionService
            LiveSessionService.end_session(session, reason="Automatic scheduled_end reached")
            updated_count += 1

    return f"Updated {updated_count} live session statuses at {now}"

@shared_task(queue='default', ignore_result=True)
def process_pending_live_session_reminders():
    """
    Periodic task to dispatch pending live session reminders (in-app + optional email).
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

        from live_classes.services import LiveSessionNotificationService
        LiveSessionNotificationService.notify_starting_soon(session, send_email=reminder.send_email)

        reminder.status = ReminderStatus.SENT
        reminder.sent_at = now
        reminder.save(update_fields=['status', 'sent_at'])
        processed_count += 1

    return f"Processed {processed_count} live session reminders at {now}"
