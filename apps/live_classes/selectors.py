from django.db.models import QuerySet
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus
from live_classes.models import (
    LiveSession,
    LiveSessionAttendance,
    LiveSessionEvent,
    LiveStatus,
)

#--------------------------------------------------------------
# LiveSessionSelector
#--------------------------------------------------------------

class LiveSessionSelector:

    @classmethod
    def get_student_categorized_live_classes(cls, student, course_id=None) -> dict:
        """
        Categorizes live sessions into live_now, upcoming, and past for a student.
        Calculates backend authoritative state to prevent relying on stale DB status or frontend clocks.
        """
        now = timezone.now()

        # Enrolled courses
        enrolled_course_ids = list(Enrollment.objects.filter(
            student=student,
            status=EnrollmentStatus.ACTIVE
        ).values_list('course_id', flat=True))

        if enrolled_course_ids:
            from courses.models import Course
            from features.services import CourseFeatureService
            valid_course_ids = []
            for c_id in enrolled_course_ids:
                try:
                    c = Course.objects.get(id=c_id)
                    if CourseFeatureService.has_feature(c, 'LIVE_CLASS'):
                        valid_course_ids.append(c_id)
                except Course.DoesNotExist:
                    continue
            enrolled_course_ids = valid_course_ids

        queryset = LiveSession.objects.filter(
            course_id__in=enrolled_course_ids
        ).select_related('course', 'course__academy', 'host').prefetch_related('reminders')

        if course_id:
            queryset = queryset.filter(course_id=course_id)

        live_now = []
        upcoming = []
        past = []

        for session in queryset:
            effective = session.calculate_effective_status(now)

            if effective == LiveStatus.LIVE and now <= session.scheduled_end and session.actual_ended_at is None:
                live_now.append(session)
            elif effective == LiveStatus.SCHEDULED and now < session.scheduled_start:
                upcoming.append(session)
            else:
                past.append(session)

        return {
            'live_now': live_now,
            'upcoming': upcoming,
            'past': past,
        }

    @classmethod
    def get_academy_live_sessions(cls, academy) -> QuerySet[LiveSession]:
        """
        Retrieves all live sessions belonging to a specific academy.
        """
        from django.db.models import Q
        return LiveSession.objects.filter(
            Q(course__academy=academy) | Q(course__isnull=True, created_by__academy=academy)
        ).select_related('course', 'host', 'created_by').prefetch_related('reminders').order_by('-scheduled_start')

    @classmethod
    def get_session_events(cls, session: LiveSession) -> QuerySet[LiveSessionEvent]:
        """
        Retrieves lifecycle event logs for a session.
        """
        return LiveSessionEvent.objects.filter(session=session).order_by('-occurred_at')

    @classmethod
    def get_session_attendance_summary(cls, session: LiveSession) -> QuerySet[LiveSessionAttendance]:
        """
        Retrieves attendance summary for a session.
        """
        return LiveSessionAttendance.objects.filter(
            participant__session=session
        ).select_related('participant', 'participant__user').order_by('-joined_at')
