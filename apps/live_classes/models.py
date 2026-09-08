from core.models import BaseModel
from django.db import models
from django.utils import timezone

#--------------------------------------------------------------
# SessionMode
#--------------------------------------------------------------

class SessionMode(models.TextChoices):
    EXTERNAL = 'EXTERNAL', 'External Link'
    NATIVE = 'NATIVE', 'Native WebRTC/SFU'

#--------------------------------------------------------------
# LiveProvider
#--------------------------------------------------------------

class LiveProvider(models.TextChoices):
    GOOGLE_MEET = 'GOOGLE_MEET', 'Google Meet'
    ZOOM = 'ZOOM', 'Zoom'
    MICROSOFT_TEAMS = 'MICROSOFT_TEAMS', 'Microsoft Teams'
    CUSTOM = 'CUSTOM', 'Custom Link'
    NATIVE_SFU = 'NATIVE_SFU', 'Native SFU'

#--------------------------------------------------------------
# LiveStatus
#--------------------------------------------------------------

class LiveStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    LIVE = 'LIVE', 'Live'
    ENDED = 'ENDED', 'Ended'
    CANCELLED = 'CANCELLED', 'Cancelled'

#--------------------------------------------------------------
# ReminderStatus
#--------------------------------------------------------------

class ReminderStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    SENT = 'SENT', 'Sent'
    CANCELLED = 'CANCELLED', 'Cancelled'
    FAILED = 'FAILED', 'Failed'

#--------------------------------------------------------------
# ParticipantRole
#--------------------------------------------------------------

class ParticipantRole(models.TextChoices):
    HOST = 'HOST', 'Host'
    CO_HOST = 'CO_HOST', 'Co-Host'
    SPEAKER = 'SPEAKER', 'Speaker'
    ATTENDEE = 'ATTENDEE', 'Attendee'

#--------------------------------------------------------------
# 1. Primary Live Session Model
#--------------------------------------------------------------

class LiveSession(BaseModel):
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='live_sessions',
        null=True,
        blank=True
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    session_mode = models.CharField(
        max_length=20,
        choices=SessionMode.choices,
        default=SessionMode.EXTERNAL
    )
    provider = models.CharField(
        max_length=30,
        choices=LiveProvider.choices,
        default=LiveProvider.GOOGLE_MEET
    )

    scheduled_start = models.DateTimeField(db_index=True)
    scheduled_end = models.DateTimeField(db_index=True)

    actual_started_at = models.DateTimeField(null=True, blank=True)
    actual_ended_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=LiveStatus.choices,
        default=LiveStatus.SCHEDULED,
        db_index=True
    )

    meeting_url = models.URLField(blank=True, default='')
    native_room_id = models.CharField(max_length=100, blank=True, default='')

    host = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='hosted_sessions',
        null=True,
        blank=True
    )

    max_participants = models.PositiveIntegerField(default=100)

    allow_chat = models.BooleanField(default=True)
    allow_raise_hand = models.BooleanField(default=True)
    allow_screen_share = models.BooleanField(default=True)

    recording_enabled = models.BooleanField(default=False)
    is_recording_active = models.BooleanField(default=False)
    send_email_notification = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_live_sessions'
    )

    class Meta:
        db_table = 'live_sessions'
        ordering = ['scheduled_start']

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def start_at(self):
        return self.scheduled_start

    @property
    def end_at(self):
        return self.scheduled_end

    @property
    def meeting_link(self):
        return self.meeting_url


    def calculate_effective_status(self, now=None) -> str:
        """
        Calculates the authoritative effective status.
        Overrides stale database status if time boundaries have passed.
        """
        if not now:
            now = timezone.now()

        if self.status == LiveStatus.CANCELLED:
            return LiveStatus.CANCELLED

        if self.status == LiveStatus.DRAFT:
            return LiveStatus.DRAFT

        if self.actual_ended_at is not None or self.status == LiveStatus.ENDED:
            return LiveStatus.ENDED

        # If current time is past the scheduled end time, it is effectively ENDED
        if now >= self.scheduled_end:
            return LiveStatus.ENDED

        # If current time is between start and end, and session has started or status is LIVE
        if self.scheduled_start <= now < self.scheduled_end:
            if self.status in [LiveStatus.LIVE, LiveStatus.SCHEDULED]:
                return LiveStatus.LIVE

        if now < self.scheduled_start:
            return LiveStatus.SCHEDULED

        return self.status

    @property
    def is_joinable(self) -> bool:
        """
        Security check: determines if students can join.
        """
        now = timezone.now()
        effective = self.calculate_effective_status(now)
        if effective != LiveStatus.LIVE:
            return False
        if now > self.scheduled_end or self.actual_ended_at is not None:
            return False
        return True

#--------------------------------------------------------------
# 2. Live Session Reminder Model
#--------------------------------------------------------------

class LiveSessionReminder(BaseModel):
    session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name='reminders',
        null=True,
        blank=True
    )
    reminder_type = models.CharField(max_length=50, default='EMAIL')
    minutes_before = models.PositiveIntegerField(default=60)
    scheduled_for = models.DateTimeField(db_index=True)
    send_email = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ReminderStatus.choices,
        default=ReminderStatus.PENDING,
        db_index=True
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        db_table = 'live_session_reminders'
        ordering = ['scheduled_for']

    def __str__(self):
        return f"Reminder {self.minutes_before}m before {self.session.title} ({self.status})"

#--------------------------------------------------------------
# 3. Live Session Participant Model
#--------------------------------------------------------------

class LiveSessionParticipant(BaseModel):
    session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name='participants',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    role = models.CharField(
        max_length=30,
        choices=ParticipantRole.choices,
        default=ParticipantRole.ATTENDEE
    )

    class Meta:
        db_table = 'live_session_participants'
        unique_together = ('session', 'user')

    def __str__(self):
        return f"{self.user.email} as {self.role} in {self.session.title}"

#--------------------------------------------------------------
# 4. Live Session Attendance Model
#--------------------------------------------------------------

class LiveSessionAttendance(BaseModel):
    participant = models.ForeignKey(
        LiveSessionParticipant,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        null=True,
        blank=True
    )
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'live_session_attendances'
        ordering = ['-joined_at']

    def __str__(self):
        return f"Attendance for {self.participant} ({self.duration_seconds}s)"

class LiveSessionRecording(BaseModel):
    session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name='recordings',
        null=True,
        blank=True
    )
    media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    duration_seconds = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default='COMPLETED')

    class Meta:
        db_table = 'live_session_recordings'

    def __str__(self):
        return f"Recording for {self.session.title}"

class LiveSessionEvent(BaseModel):
    session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name='events',
        null=True,
        blank=True
    )
    event_type = models.CharField(max_length=50, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'live_session_events'
        ordering = ['-occurred_at']

    def __str__(self):
        return f"{self.event_type} on {self.session.title} at {self.occurred_at}"
