from django.contrib import admin
from live_classes.models import (
    LiveSession,
    LiveSessionAttendance,
    LiveSessionEvent,
    LiveSessionParticipant,
    LiveSessionRecording,
    LiveSessionReminder,
)


class LiveSessionReminderInline(admin.TabularInline):
    model = LiveSessionReminder
    extra = 0

class LiveSessionEventInline(admin.TabularInline):
    model = LiveSessionEvent
    extra = 0
    readonly_fields = ('event_type', 'occurred_at', 'payload')

@admin.register(LiveSession)
class LiveSessionAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'course',
        'session_mode',
        'provider',
        'scheduled_start',
        'scheduled_end',
        'status',
        'host'
    )
    list_filter = ('status', 'session_mode', 'provider', 'scheduled_start')
    search_fields = ('title', 'description', 'course__title')
    inlines = [LiveSessionReminderInline, LiveSessionEventInline]

@admin.register(LiveSessionReminder)
class LiveSessionReminderAdmin(admin.ModelAdmin):
    list_display = ('session', 'minutes_before', 'scheduled_for', 'status', 'sent_at')
    list_filter = ('status', 'minutes_before', 'scheduled_for')
    search_fields = ('session__title',)

@admin.register(LiveSessionParticipant)
class LiveSessionParticipantAdmin(admin.ModelAdmin):
    list_display = ('session', 'user', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('session__title', 'user__email', 'user__full_name')

@admin.register(LiveSessionAttendance)
class LiveSessionAttendanceAdmin(admin.ModelAdmin):
    list_display = ('participant', 'joined_at', 'left_at', 'duration_seconds')
    list_filter = ('joined_at',)

@admin.register(LiveSessionRecording)
class LiveSessionRecordingAdmin(admin.ModelAdmin):
    list_display = ('session', 'duration_seconds', 'status', 'created_at')

@admin.register(LiveSessionEvent)
class LiveSessionEventAdmin(admin.ModelAdmin):
    list_display = ('session', 'event_type', 'occurred_at')
    list_filter = ('event_type', 'occurred_at')
