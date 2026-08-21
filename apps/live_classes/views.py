from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from courses.models import Course
from live_classes.models import LiveSession
from live_classes.selectors import LiveSessionSelector
from live_classes.services import LiveSessionService
from live_classes.serializers import (
    LiveSessionSerializer,
    LiveSessionCreateSerializer,
    LiveSessionUpdateSerializer,
    EndSessionRequestSerializer,
    CancelSessionRequestSerializer,
    StudentLiveClassesResponseSerializer,
)


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
    GET /api/v1/live-sessions/
    POST /api/v1/live-sessions/
    GET /api/v1/live-sessions/{id}/
    PATCH /api/v1/live-sessions/{id}/
    DELETE /api/v1/live-sessions/{id}/
    POST /api/v1/live-sessions/{id}/start/
    POST /api/v1/live-sessions/{id}/end/
    POST /api/v1/live-sessions/{id}/cancel/
    POST /api/v1/live-sessions/{id}/join/
    POST /api/v1/live-sessions/{id}/leave/
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

        course_id = serializer.validated_data['course_id']
        try:
            if academy:
                course = Course.objects.get(id=course_id, academy=academy)
            else:
                course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            raise ValidationError({"course_id": ["Course not found or does not belong to your academy."]})

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
            status=serializer.validated_data.get('status', 'SCHEDULED')
        )

        session_data = LiveSessionSerializer(session).data
        response_data = {
            "success": True,
            "message": "Live session created successfully.",
            "data": session_data,
            "notification_status": "queued",
            "email_status": "queued" if serializer.validated_data.get('send_email', False) else "disabled",
            "reminder_status": "scheduled"
        }
        # Copy direct properties at top level for backward compatibility
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
