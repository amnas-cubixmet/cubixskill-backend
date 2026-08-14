from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

from courses.models import Course
from discussions_chat.models import (
    DiscussionThread,
    DiscussionReply,
    ChatRoom,
    ChatMessage,
    CommunicationReport,
    ReportStatus,
)
from discussions_chat.selectors import DiscussionSelector, ChatSelector
from discussions_chat.services import DiscussionService, ChatService
from discussions_chat.serializers import (
    DiscussionThreadSerializer,
    DiscussionReplySerializer,
    CreateThreadSerializer,
    CreateReplySerializer,
    ChatRoomSerializer,
    ChatMessageSerializer,
    CommunicationReportSerializer,
    CreateReportSerializer,
)

#--------------------------------------------------------------
# 1. Course Discussion ViewSet
#--------------------------------------------------------------

class CourseDiscussionViewSet(viewsets.ModelViewSet):
    """
    API viewset for Course Discussion Threads & Replies.
    GET /api/v1/courses/{course_id}/discussions/
    POST /api/v1/courses/{course_id}/discussions/
    GET /api/v1/discussions/{id}/
    PATCH /api/v1/discussions/{id}/
    DELETE /api/v1/discussions/{id}/
    GET /api/v1/discussions/{id}/replies/
    POST /api/v1/discussions/{id}/replies/
    POST /api/v1/discussions/{id}/pin/
    POST /api/v1/discussions/{id}/lock/
    POST /api/v1/discussions/{id}/accept-answer/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DiscussionThreadSerializer

    def get_queryset(self):
        course_id = self.kwargs.get('course_id')
        if course_id:
            try:
                course = Course.objects.get(id=course_id)
                thread_type = self.request.query_params.get('thread_type')
                search = self.request.query_params.get('search')
                return DiscussionSelector.get_course_threads(course, thread_type=thread_type, search=search)
            except Course.DoesNotExist:
                return DiscussionThread.objects.none()
        return DiscussionThread.objects.all()

    def create(self, request, course_id=None):
        if not course_id:
            course_id = request.data.get('course_id')

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            raise ValidationError({"course_id": "Course not found."})

        serializer = CreateThreadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        thread = DiscussionService.create_thread(
            course=course,
            user=request.user,
            title=serializer.validated_data['title'],
            content=serializer.validated_data['content'],
            thread_type=serializer.validated_data.get('thread_type', 'DISCUSSION'),
            media_file_ids=serializer.validated_data.get('media_file_ids', [])
        )

        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None, *args, **kwargs):
        thread = self.get_object()
        if thread.created_by != request.user and not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("You do not have permission to edit this thread.")

        content = request.data.get('content')
        title = request.data.get('title')
        if content:
            thread.content = content
        if title:
            thread.title = title
        thread.save()

        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_200_OK)

    def destroy(self, request, pk=None, *args, **kwargs):
        thread = self.get_object()
        DiscussionService.soft_delete_thread(thread, request.user)
        return Response({"detail": "Thread removed successfully."}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post'])
    def replies(self, request, pk=None, course_id=None):
        thread = self.get_object()

        if request.method == 'GET':
            replies = DiscussionSelector.get_thread_replies(thread)
            serializer = DiscussionReplySerializer(replies, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            serializer = CreateReplySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            reply = DiscussionService.add_reply(
                thread=thread,
                user=request.user,
                content=serializer.validated_data['content'],
                parent_reply_id=serializer.validated_data.get('parent_reply_id'),
                media_file_ids=serializer.validated_data.get('media_file_ids', [])
            )
            return Response(DiscussionReplySerializer(reply).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def pin(self, request, pk=None, course_id=None):
        if not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Only staff can pin threads.")
        thread = self.get_object()
        is_pinned = request.data.get('is_pinned', not thread.is_pinned)
        thread = DiscussionService.toggle_pin_thread(thread, request.user, is_pinned=is_pinned)
        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None, course_id=None):
        if not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Only staff can lock threads.")
        thread = self.get_object()
        is_locked = request.data.get('is_locked', not thread.is_locked)
        thread = DiscussionService.toggle_lock_thread(thread, request.user, is_locked=is_locked)
        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='accept-answer')
    def accept_answer(self, request, pk=None, course_id=None):
        thread = self.get_object()
        reply_id = request.data.get('reply_id')
        try:
            reply = DiscussionReply.objects.get(id=reply_id, thread=thread)
        except DiscussionReply.DoesNotExist:
            raise ValidationError({"reply_id": "Reply not found."})

        updated_thread = DiscussionService.mark_accepted_answer(thread, reply, request.user)
        return Response(DiscussionThreadSerializer(updated_thread).data, status=status.HTTP_200_OK)
#--------------------------------------------------------------
# 2. Discussion Reply Model
#--------------------------------------------------------------

class ChatRoomViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for Chat Rooms and Message History.
    GET /api/v1/chat/rooms/
    GET /api/v1/chat/rooms/{id}/
    GET /api/v1/chat/rooms/{id}/messages/
    POST /api/v1/chat/rooms/{id}/read/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChatRoomSerializer

    def get_queryset(self):
        return ChatRoom.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        room_dicts = ChatSelector.get_user_chat_rooms(request.user)
        results = []
        for r_dict in room_dicts:
            data = ChatRoomSerializer(r_dict['room']).data
            data['unread_count'] = r_dict['unread_count']
            results.append(data)
        return Response(results, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        room = self.get_object()
        if not ChatService.validate_chat_access(request.user, room):
            raise PermissionDenied("Chat is disabled for this course or student has no access.")

        data = ChatRoomSerializer(room).data
        data['unread_count'] = ChatService.get_unread_count(room, request.user)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        room = self.get_object()
        if not ChatService.validate_chat_access(request.user, room):
            raise PermissionDenied("Chat is disabled for this course or student has no access.")

        before_id = request.query_params.get('before_id')
        limit = int(request.query_params.get('limit', 50))

        messages = ChatSelector.get_room_messages(room, before_id=before_id, limit=limit)
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        room = self.get_object()
        if not ChatService.validate_chat_access(request.user, room):
            raise PermissionDenied("Chat is disabled for this course or student has no access.")

        unread = ChatService.mark_room_as_read(room, request.user)
        return Response({"unread_count": unread}, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# 3. Communication Report ViewSet
#--------------------------------------------------------------

class CommunicationReportViewSet(viewsets.ModelViewSet):
    """
    API endpoint for content moderation reports.
    POST /api/v1/chat/reports/
    GET /api/v1/chat/reports/
    POST /api/v1/chat/reports/{id}/resolve/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommunicationReportSerializer

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_staff', False):
            academy = getattr(user, 'academy', None)
            return ChatSelector.get_communication_reports(academy=academy)
        return CommunicationReport.objects.filter(reported_by=user)

    def create(self, request, *args, **kwargs):
        serializer = CreateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        thread = None
        reply = None
        message = None

        if serializer.validated_data.get('thread_id'):
            thread = DiscussionThread.objects.get(id=serializer.validated_data['thread_id'])
        if serializer.validated_data.get('reply_id'):
            reply = DiscussionReply.objects.get(id=serializer.validated_data['reply_id'])
        if serializer.validated_data.get('message_id'):
            message = ChatMessage.objects.get(id=serializer.validated_data['message_id'])

        report = ChatService.create_report(
            user=request.user,
            reason=serializer.validated_data['reason'],
            thread=thread,
            reply=reply,
            message=message,
            description=serializer.validated_data.get('description', '')
        )

        return Response(CommunicationReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Only staff can resolve reports.")
        report = self.get_object()
        report.status = ReportStatus.RESOLVED
        report.reviewed_by = request.user
        report.reviewed_at = timezone.now()
        report.save()

        return Response(CommunicationReportSerializer(report).data, status=status.HTTP_200_OK)
