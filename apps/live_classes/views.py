import logging

from courses.models import Course
from django.utils import timezone
from live_classes.models import (
    LiveSession,
    LiveSessionAttendance,
    ParticipantRole,
)
from live_classes.selectors import LiveSessionSelector
from live_classes.serializers import (
    CancelSessionRequestSerializer,
    EndSessionRequestSerializer,
    LiveSessionAttendanceSerializer,
    LiveSessionCreateSerializer,
    LiveSessionSerializer,
    LiveSessionUpdateSerializer,
    StudentLiveClassesResponseSerializer,
)
from live_classes.services import LiveSessionService
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


#--------------------------------------------------------------
# 1. Student Live Classes View
#--------------------------------------------------------------

class StudentLiveClassesView(APIView):
    """
    Student API returning live classes categorized into live_now, upcoming, and past.
    Backend calculates authoritative effective status to enforce accurate state regardless of client clocks.
    GET /api/v1/student/live-classes/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get('course_id')
        categorized = LiveSessionSelector.get_student_categorized_live_classes(
            student=request.user,
            course_id=course_id
        )
        serializer = StudentLiveClassesResponseSerializer(categorized)
        return Response(serializer.data, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# 2. Live Session View Set
#--------------------------------------------------------------
class LiveSessionViewSet(viewsets.ModelViewSet):
    """
    Academy staff and student endpoints to manage and access live sessions.
    GET /api/v1/live-classes/live-sessions/
    POST /api/v1/live-classes/live-sessions/
    GET /api/v1/live-classes/live-sessions/{id}/
    PATCH /api/v1/live-classes/live-sessions/{id}/
    DELETE /api/v1/live-classes/live-sessions/{id}/
    GET /api/v1/live-classes/live-sessions/summary/
    POST /api/v1/live-classes/live-sessions/{id}/start/
    POST /api/v1/live-classes/live-sessions/{id}/end/
    POST /api/v1/live-classes/live-sessions/{id}/cancel/
    POST /api/v1/live-classes/live-sessions/{id}/join/
    POST /api/v1/live-classes/live-sessions/{id}/leave/
    GET /api/v1/live-classes/live-sessions/{id}/attendance/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LiveSessionSerializer

    def get_queryset(self):
        user = self.request.user
        course_id = self.request.query_params.get('course') or self.request.query_params.get('course_id')
        if hasattr(user, 'academy') and user.academy:
            qs = LiveSessionSelector.get_academy_live_sessions(user.academy)
        else:
            qs = LiveSession.objects.select_related('course', 'host', 'created_by').all()
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = LiveSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        academy = getattr(user, 'academy', None)

        course_id = serializer.validated_data.get('course_id')
        course = None
        if course_id:
            try:
                if academy:
                    course = Course.objects.get(id=course_id, academy=academy)
                else:
                    course = Course.objects.get(id=course_id)
            except Course.DoesNotExist:
                raise ValidationError({"course_id": ["Course not found or does not belong to your academy."]})

        try:
            session = LiveSessionService.create_session(
                course=course,
                title=serializer.validated_data['title'],
                scheduled_start=serializer.validated_data['scheduled_start'],
                scheduled_end=serializer.validated_data['scheduled_end'],
                created_by=user,
                description=serializer.validated_data.get('description', ''),
                session_mode=serializer.validated_data.get('session_mode', 'EXTERNAL'),
                provider=serializer.validated_data.get('provider', 'GOOGLE_MEET'),
                meeting_url=serializer.validated_data.get('meeting_url', ''),
                max_participants=serializer.validated_data.get('max_participants', 100),
                recording_enabled=serializer.validated_data.get('recording_enabled', False),
                send_email=serializer.validated_data.get('send_email', False),
                reminders_minutes_before=serializer.validated_data.get('reminders_minutes_before', [60]),
                announce_on_create=serializer.validated_data.get('announce_on_create', False),
                status=serializer.validated_data.get('status', 'SCHEDULED')
            )
        except Exception as exc:
            logger.exception(f"Live session creation failed for course {course_id}: {exc}")
            raise

        session_data = LiveSessionSerializer(session).data
        response_data = {
            "success": True,
            "message": "Live session created successfully.",
            "data": session_data,
            "notification_status": "queued",
            "email_status": "queued" if serializer.validated_data.get('send_email', False) else "disabled",
            "reminder_status": "scheduled"
        }
        response_data.update(session_data)

        return Response(response_data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        session = self.get_object()
        serializer = LiveSessionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        updated_session = LiveSessionService.update_session(
            session=session,
            send_email=serializer.validated_data.get('send_email', False),
            **serializer.validated_data
        )

        return Response(LiveSessionSerializer(updated_session).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self.get_queryset()
        now = timezone.now()

        total = qs.count()
        live_now = 0
        upcoming = 0
        completed = 0
        cancelled = 0
        recorded = 0

        for session in qs:
            st = session.calculate_effective_status(now)
            if st == 'LIVE':
                live_now += 1
            elif st == 'SCHEDULED':
                upcoming += 1
            elif st == 'COMPLETED':
                completed += 1
            elif st == 'CANCELLED':
                cancelled += 1
            if session.recording_enabled or session.recordings.exists():
                recorded += 1

        avg_attendance_rate = 0
        completed_sessions = [s for s in qs if s.calculate_effective_status(now) == 'COMPLETED']
        if completed_sessions:
            rates = []
            for s in completed_sessions:
                part_count = s.participants.filter(role=ParticipantRole.ATTENDEE).count()
                if part_count > 0:
                    joined_count = LiveSessionAttendance.objects.filter(participant__session=s).values('participant').distinct().count()
                    rates.append((joined_count / part_count) * 100)
            if rates:
                avg_attendance_rate = round(sum(rates) / len(rates))

        return Response({
            "total": total,
            "live_now": live_now,
            "upcoming": upcoming,
            "completed": completed,
            "cancelled": cancelled,
            "recorded": recorded,
            "avg_attendance_rate": avg_attendance_rate,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        session = self.get_object()
        started_session = LiveSessionService.start_session(session, host_user=request.user)
        return Response(LiveSessionSerializer(started_session).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        session = self.get_object()
        serializer = EndSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('reason', '')
        ended_session = LiveSessionService.end_session(
            session=session,
            ended_by=request.user,
            reason=reason
        )

        return Response(LiveSessionSerializer(ended_session).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        session = self.get_object()
        serializer = CancelSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('reason', '')
        cancelled_session = LiveSessionService.cancel_session(
            session=session,
            cancelled_by=request.user,
            reason=reason
        )

        return Response(LiveSessionSerializer(cancelled_session).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        session = self.get_object()
        participant, attendance, join_info = LiveSessionService.join_session(
            session=session,
            user=request.user
        )
        return Response(join_info, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        session = self.get_object()
        LiveSessionService.leave_session(session=session, user=request.user)
        return Response({"detail": "Successfully left the session."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def attendance(self, request, pk=None):
        session = self.get_object()
        attendances = LiveSessionSelector.get_session_attendance_summary(session)
        serializer = LiveSessionAttendanceSerializer(attendances, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
