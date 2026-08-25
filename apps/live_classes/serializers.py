from rest_framework import serializers
from live_classes.models import (
    LiveSession,
    LiveSessionReminder,
    LiveSessionParticipant,
    LiveSessionAttendance,
    LiveSessionRecording,
    LiveSessionEvent,
)
#--------------------------------------------------------------
# 1. Live Session Reminder Serializer
#--------------------------------------------------------------

class LiveSessionReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveSessionReminder
        fields = [
            'id',
            'reminder_type',
            'minutes_before',
            'scheduled_for',
            'status',
            'sent_at',
        ]
        read_only_fields = fields

#--------------------------------------------------------------
# 2. Live Session Participant Serializer
#--------------------------------------------------------------

class LiveSessionParticipantSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = LiveSessionParticipant
        fields = [
            'id',
            'user',
            'user_email',
            'user_name',
            'role',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

#--------------------------------------------------------------
# 3. Live Session Attendance Serializer
#--------------------------------------------------------------
class LiveSessionAttendanceSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='participant.user.email', read_only=True)

    class Meta:
        model = LiveSessionAttendance
        fields = [
            'id',
            'participant',
            'user_email',
            'joined_at',
            'left_at',
            'duration_seconds',
        ]
        read_only_fields = fields

#--------------------------------------------------------------
# 4. Live Session Event Serializer
#--------------------------------------------------------------
class LiveSessionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveSessionEvent
        fields = [
            'id',
            'event_type',
            'occurred_at',
            'payload',
        ]
        read_only_fields = fields

#--------------------------------------------------------------
# 5. Live Session Serializer
#--------------------------------------------------------------
class LiveSessionSerializer(serializers.ModelSerializer):
    effective_status = serializers.SerializerMethodField()
    is_joinable = serializers.SerializerMethodField()
    reminders = LiveSessionReminderSerializer(many=True, read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    host_name = serializers.SerializerMethodField()

    class Meta:
        model = LiveSession
        fields = [
            'id',
            'course',
            'course_title',
            'title',
            'description',
            'session_mode',
            'provider',
            'scheduled_start',
            'scheduled_end',
            'actual_started_at',
            'actual_ended_at',
            'status',
            'effective_status',
            'is_joinable',
            'meeting_url',
            'native_room_id',
            'host',
            'host_name',
            'max_participants',
            'allow_chat',
            'allow_raise_hand',
            'allow_screen_share',
            'recording_enabled',
            'is_recording_active',
            'reminders',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'actual_started_at',
            'actual_ended_at',
            'created_at',
            'updated_at',
        ]

    def get_effective_status(self, obj) -> str:
        return obj.calculate_effective_status()

    def get_is_joinable(self, obj) -> bool:
        return obj.is_joinable

    def get_host_name(self, obj) -> str | None:
        if obj.host:
            return getattr(obj.host, 'full_name', None) or obj.host.email
        return None

#--------------------------------------------------------------
# 6. Live Session Create Serializer
#--------------------------------------------------------------
class LiveSessionCreateSerializer(serializers.Serializer):
    course_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()
    session_mode = serializers.CharField(required=False, default='EXTERNAL')
    provider = serializers.CharField(required=False, default='GOOGLE_MEET')
    meeting_url = serializers.URLField(required=False, allow_blank=True, default='')
    max_participants = serializers.IntegerField(required=False, default=100)
    recording_enabled = serializers.BooleanField(required=False, default=False)
    send_email = serializers.BooleanField(required=False, default=False)
    reminders_minutes_before = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=[60]
    )
    announce_on_create = serializers.BooleanField(required=False, default=False)
    status = serializers.CharField(required=False, default='SCHEDULED')

#--------------------------------------------------------------
# 7. Live Session Update Serializer
#--------------------------------------------------------------
class LiveSessionUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    scheduled_start = serializers.DateTimeField(required=False)
    scheduled_end = serializers.DateTimeField(required=False)
    session_mode = serializers.CharField(required=False)
    provider = serializers.CharField(required=False)
    meeting_url = serializers.URLField(required=False, allow_blank=True)
    max_participants = serializers.IntegerField(required=False)
    recording_enabled = serializers.BooleanField(required=False)
    send_email = serializers.BooleanField(required=False, default=False)

#--------------------------------------------------------------
# 8. End Session Request Serializer
#--------------------------------------------------------------
class EndSessionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')

#--------------------------------------------------------------
# 9. Cancel Session Request Serializer
#--------------------------------------------------------------
class CancelSessionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')

#--------------------------------------------------------------
# 10. Student Live Classes Response Serializer
#--------------------------------------------------------------
class StudentLiveClassesResponseSerializer(serializers.Serializer):
    live_now = LiveSessionSerializer(many=True)
    upcoming = LiveSessionSerializer(many=True)
    past = LiveSessionSerializer(many=True)
