from courses.models import Course
from discussions_chat.models import (
    ChatMessage,
    ChatRoom,
    CommunicationReport,
    DiscussionReply,
    DiscussionThread,
    ReportStatus,
)
from discussions_chat.selectors import ChatSelector, DiscussionSelector
from discussions_chat.serializers import (
    ChatMessageSerializer,
    ChatRoomSerializer,
    CommunicationReportSerializer,
    CreateReplySerializer,
    CreateReportSerializer,
    CreateThreadSerializer,
    DiscussionReplySerializer,
    DiscussionThreadSerializer,
)
from discussions_chat.services import ChatService, DiscussionService
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError

#--------------------------------------------------------------
# 1. Course Discussion ViewSet
#--------------------------------------------------------------
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100

class CourseDiscussionViewSet(viewsets.ModelViewSet):
    """
    API viewset for Course & Academy Discussion Threads & Replies.
    GET /api/v1/discussions/discussions/
    POST /api/v1/discussions/discussions/
    GET /api/v1/discussions/discussions/{id}/
    PATCH /api/v1/discussions/discussions/{id}/
    DELETE /api/v1/discussions/discussions/{id}/
    GET /api/v1/discussions/discussions/{id}/replies/
    POST /api/v1/discussions/discussions/{id}/replies/
    POST /api/v1/discussions/discussions/{id}/pin/
    POST /api/v1/discussions/discussions/{id}/lock/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DiscussionThreadSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        course_id = self.kwargs.get('course_id') or self.request.query_params.get('course_id')
        thread_type = self.request.query_params.get('thread_type')
        search = self.request.query_params.get('search')
        status_filter = self.request.query_params.get('status')
        ordering = self.request.query_params.get('ordering', 'recent')

        if course_id and course_id != 'general':
            try:
                course = Course.objects.get(id=course_id)
                from features.services import CourseFeatureService
                CourseFeatureService.require_enabled(course, 'COURSE_DISCUSSION', user=self.request.user)
            except (Course.DoesNotExist, ValueError):
                pass

        return DiscussionSelector.get_threads_for_user(
            user=self.request.user,
            course_id=course_id,
            thread_type=thread_type,
            search=search,
            status_filter=status_filter,
            ordering=ordering
        )

    def create(self, request, course_id=None):
        if not course_id:
            course_id = request.data.get('course_id')

        course = None
        if course_id and course_id != 'general':
            try:
                course = Course.objects.get(id=course_id)
                from features.services import CourseFeatureService
                CourseFeatureService.require_enabled(course, 'COURSE_DISCUSSION', user=request.user)
            except (Course.DoesNotExist, ValueError):
                raise ValidationError({"course_id": "Specified course was not found."})

        serializer = CreateThreadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        thread = DiscussionService.create_thread(
            course=course,
            user=request.user,
            title=serializer.validated_data['title'],
            content=serializer.validated_data['content'],
            thread_type=serializer.validated_data.get('thread_type', 'DISCUSSION'),
            media_file_ids=serializer.validated_data.get('media_file_ids', []),
            send_email=serializer.validated_data.get('send_email', False),
            publish_option=serializer.validated_data.get('publish_option', 'now')
        )

        thread_data = DiscussionThreadSerializer(thread).data
        academy_id = thread.academy.id if thread.academy else None
        DiscussionService.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.created',
            data=thread_data
        )

        return Response(thread_data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='announcement-cost-preview')
    def announcement_cost_preview(self, request):
        """
        API endpoint for frontend to preview Announcement and Email Delivery credit cost.
        Calculates eligible recipients and dynamic pricing rates from central Control Panel settings.
        """
        course_id = request.data.get('course_id')
        send_email = str(request.data.get('send_email', 'false')).lower() in ('true', '1', 'yes')

        course = None
        if course_id and course_id != 'general':
            try:
                course = Course.objects.get(id=course_id)
            except (Course.DoesNotExist, ValueError):
                pass

        academy = course.academy if course else getattr(request.user, 'academy', None)
        cost_info = DiscussionService.calculate_announcement_cost(course=course, academy=academy, send_email=send_email)

        return Response({
            'announcement_price': cost_info['announcement_price'],
            'email_enabled': cost_info['email_enabled'],
            'email_recipient_count': cost_info['email_recipient_count'],
            'email_unit_price': cost_info['email_unit_price'],
            'email_cost': cost_info['email_cost'],
            'total_cost': cost_info['total_cost'],
            'academy_credit_balance': cost_info['academy_credit_balance'],
            'has_sufficient_credits': cost_info['has_sufficient_credits']
        }, status=status.HTTP_200_OK)

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

        thread_data = DiscussionThreadSerializer(thread).data
        academy_id = thread.academy.id if thread.academy else None
        DiscussionService.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.updated',
            data=thread_data
        )

        return Response(thread_data, status=status.HTTP_200_OK)

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
    POST /api/v1/chat/rooms/get-or-create-personal/
    POST /api/v1/chat/rooms/{id}/send-message/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChatRoomSerializer

    def get_queryset(self):
        return ChatRoom.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        course_id = request.query_params.get('course_id')
        room_type = request.query_params.get('room_type')

        room_dicts = ChatSelector.get_user_chat_rooms(request.user)
        results = []
        for r_dict in room_dicts:
            room = r_dict['room']
            if course_id and str(room.course_id) != course_id:
                continue
            if room_type and room.room_type != room_type:
                continue

            data = ChatRoomSerializer(room).data
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

    @action(detail=False, methods=['post'], url_path='get-or-create-personal')
    def get_or_create_personal(self, request):
        course_id = request.data.get('course_id')
        student_id = request.data.get('student_id')

        if not course_id or not student_id:
            raise ValidationError({"detail": "course_id and student_id are required."})

        try:
            course = Course.objects.get(id=course_id)
        except (Course.DoesNotExist, ValueError):
            raise ValidationError({"course_id": "Specified course not found."})

        from users_roles.models import User
        try:
            student = User.objects.get(id=student_id)
        except (User.DoesNotExist, ValueError):
            raise ValidationError({"student_id": "Specified student not found."})

        room = ChatService.get_or_create_personal_room(course, student, request.user)
        data = ChatRoomSerializer(room).data
        data['unread_count'] = ChatService.get_unread_count(room, request.user)
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='get-or-create-community')
    def get_or_create_community(self, request):
        course_id = request.data.get('course_id')
        if not course_id:
            raise ValidationError({"detail": "course_id is required."})

        try:
            course = Course.objects.get(id=course_id)
        except (Course.DoesNotExist, ValueError):
            raise ValidationError({"course_id": "Specified course not found."})

        room = ChatService.get_or_create_community_room(course, request.user)
        data = ChatRoomSerializer(room).data
        data['unread_count'] = ChatService.get_unread_count(room, request.user)
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='community-groups')
    def community_groups(self, request):
        """
        List all applicable active courses for the authenticated user's Academy with effective COURSE_DISCUSSION feature state and canonical community room preview.
        """
        user = request.user
        academy = getattr(user, 'academy', None)
        if not academy and not getattr(user, 'is_staff', False):
            return Response([], status=status.HTTP_200_OK)

        from courses.models import Course
        from discussions_chat.models import RoomType
        from features.services import CourseFeatureService

        courses_qs = Course.objects.filter(is_active=True)
        if academy:
            courses_qs = courses_qs.filter(academy=academy)

        courses = list(courses_qs)
        enabled_courses = [c for c in courses if CourseFeatureService.has_feature(c, 'COURSE_DISCUSSION')]

        # Prefetch community rooms for these courses
        course_ids = [c.id for c in enabled_courses]
        rooms_dict = {}
        if course_ids:
            for r in ChatRoom.objects.filter(course_id__in=course_ids, room_type=RoomType.COURSE, is_active=True):
                if r.course_id and r.course_id not in rooms_dict:
                    rooms_dict[r.course_id] = r

        results = []
        for course in enabled_courses:
            room = rooms_dict.get(course.id)
            room_data = None
            if room:
                room_data = ChatRoomSerializer(room).data
                room_data['unread_count'] = ChatService.get_unread_count(room, user)

            thumbnail_url = None
            if hasattr(course, 'thumbnail') and course.thumbnail:
                mf = course.thumbnail
                raw_path = getattr(mf, 'url', '') or getattr(mf, 'file_url', '') or getattr(mf, 'relative_path', '') or ''
                if not raw_path:
                    storage_key = getattr(mf, 'storage_key', '') or ''
                    if storage_key:
                        raw_path = f"/media/{storage_key.lstrip('/')}"
                thumbnail_url = raw_path
            if not thumbnail_url:
                thumbnail_url = getattr(course, 'thumbnail_url', '') or None

            results.append({
                'course': {
                    'id': str(course.id),
                    'title': getattr(course, 'title', ''),
                    'subtitle': getattr(course, 'subtitle', '') or '',
                    'thumbnail': thumbnail_url,
                    'status': getattr(course, 'status', 'PUBLISHED'),
                },
                'feature_enabled': True,
                'room': room_data
            })

        # Sort results: courses with active messages first (by latest message time desc), then fallback to course title/created_at
        def get_group_sort_key(item):
            room = item.get('room')
            if room and room.get('last_message') and isinstance(room['last_message'], dict):
                t_str = room['last_message'].get('created_at')
                if t_str:
                    return (1, t_str)
            if room and room.get('last_message_at'):
                return (1, room['last_message_at'])
            return (0, '')

        results.sort(key=get_group_sort_key, reverse=True)

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='eligible-users')
    def eligible_users(self, request):
        """
        Search authorized academy/course members that the current user is allowed to start a chat with.
        Scope: Same academy or enrolled courses.
        """
        search_query = request.query_params.get('search', '').strip()
        user = request.user
        from django.db.models import Q
        from users_roles.models import User

        academy = getattr(user, 'academy', None)
        if academy:
            # Academy staff or owner: see academy members & enrolled students
            users_qs = User.objects.filter(
                Q(academy=academy) | Q(enrollments__course__academy=academy)
            ).exclude(id=user.id).distinct()
        else:
            # Student: see instructors/staff of enrolled courses or peers in enrolled courses
            enrolled_course_ids = list(user.enrollments.filter(status='ACTIVE').values_list('course_id', flat=True))
            users_qs = User.objects.filter(
                Q(academy__courses__id__in=enrolled_course_ids) | Q(enrollments__course_id__in=enrolled_course_ids)
            ).exclude(id=user.id).distinct()

        if search_query:
            users_qs = users_qs.filter(
                Q(full_name__icontains=search_query) | Q(email__icontains=search_query)
            )

        results = []
        for u in users_qs[:30]:
            avatar_url = None
            if getattr(u, 'avatar', None):
                try:
                    avatar_url = u.avatar.url
                except Exception:
                    pass

            # Check if existing DM room exists
            existing_room = ChatRoom.objects.filter(
                room_type='DIRECT',
                is_active=True,
                participants__user=user
            ).filter(participants__user=u).first()

            results.append({
                'id': str(u.id),
                'full_name': u.full_name or u.email,
                'email': u.email,
                'role': getattr(u, 'role', None) or ('ACADEMY_STAFF' if getattr(u, 'is_staff', False) else 'STUDENT'),
                'avatar': avatar_url,
                'existing_room_id': str(existing_room.id) if existing_room else None,
            })

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='search-messages')
    def search_messages(self, request, pk=None):
        """
        Search inside messages in a specific chat room.
        Enforces chat participant authorization.
        """
        room = self.get_object()
        if not ChatService.validate_chat_access(request.user, room):
            raise PermissionDenied("Chat access denied.")

        q = request.query_params.get('q', '').strip()
        if not q:
            return Response([], status=status.HTTP_200_OK)

        messages = ChatMessage.objects.filter(
            room=room,
            status='ACTIVE',
            content__icontains=q
        ).select_related('sender').order_by('-created_at')[:50]

        results = []
        for m in messages:
            results.append({
                'id': str(m.id),
                'content': m.content,
                'sender_name': m.sender.full_name if m.sender else '',
                'created_at': m.created_at.isoformat(),
            })

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='send-message')
    def send_message(self, request, pk=None):
        room = self.get_object()
        content = request.data.get('content', '')
        media_file_ids = request.data.get('media_file_ids', [])
        message_type = request.data.get('message_type', 'TEXT')

        msg = ChatService.send_message(
            room=room,
            user=request.user,
            content=content,
            message_type=message_type,
            media_file_ids=media_file_ids
        )
        return Response(ChatMessageSerializer(msg, context={'request': request}).data, status=status.HTTP_201_CREATED)

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
