from django.db.models import QuerySet, Q
from discussions_chat.models import (
    DiscussionThread,
    DiscussionReply,
    ChatRoom,
    ChatMessage,
    CommunicationReport,
    ThreadStatus,
    MessageStatus,
)
from discussions_chat.services import ChatService
from enrollments.models import Enrollment, EnrollmentStatus

#--------------------------------------------------------------
# 1. Discussion Selector
#--------------------------------------------------------------

class DiscussionSelector:

    @classmethod
    def get_course_threads(
        cls,
        course,
        thread_type: str = None,
        search: str = None
    ) -> QuerySet[DiscussionThread]:
        """
        Retrieves active discussion threads for a course.
        """
        queryset = DiscussionThread.objects.filter(
            course=course,
            status=ThreadStatus.ACTIVE
        ).select_related('created_by', 'accepted_answer').prefetch_related('attachments', 'attachments__media_file')

        if thread_type:
            queryset = queryset.filter(thread_type=thread_type)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(content__icontains=search)
            )

        return queryset.order_by('-is_pinned', '-last_activity_at')

    @classmethod
    def get_thread_replies(cls, thread: DiscussionThread) -> QuerySet[DiscussionReply]:
        """
        Retrieves active replies for a discussion thread.
        """
        return DiscussionReply.objects.filter(
            thread=thread,
            status=ThreadStatus.ACTIVE
        ).select_related('created_by', 'parent_reply').prefetch_related('attachments', 'attachments__media_file').order_by('created_at')


#--------------------------------------------------------------
# 2. Chat Selector
#--------------------------------------------------------------

class ChatSelector:

    @classmethod
    def get_user_chat_rooms(cls, user) -> list[dict]:
        """
        Retrieves all active chat rooms accessible to a user with calculated unread count.
        """
        is_staff = getattr(user, 'is_staff', False) or hasattr(user, 'academy')

        if is_staff and getattr(user, 'academy', None):
            rooms = ChatRoom.objects.filter(academy=user.academy, is_active=True)
        else:
            enrolled_course_ids = Enrollment.objects.filter(
                student=user,
                status=EnrollmentStatus.ACTIVE
            ).values_list('course_id', flat=True)

            rooms = ChatRoom.objects.filter(
                course_id__in=enrolled_course_ids,
                is_active=True
            )

        rooms = rooms.select_related('course', 'academy').order_by('-last_message_at')

        results = []
        for room in rooms:
            if ChatService.validate_chat_access(user, room):
                unread_count = ChatService.get_unread_count(room, user)
                results.append({
                    'room': room,
                    'unread_count': unread_count
                })

        return results

    @classmethod
    def get_room_messages(cls, room: ChatRoom, before_id: str = None, limit: int = 50) -> QuerySet[ChatMessage]:
        """
        Retrieves paginated chat messages for REST API history.
        """
        queryset = ChatMessage.objects.filter(
            room=room,
            status=MessageStatus.ACTIVE
        ).select_related('sender', 'reply_to').prefetch_related('attachments', 'attachments__media_file')

        if before_id:
            try:
                before_msg = ChatMessage.objects.get(id=before_id)
                queryset = queryset.filter(created_at__lt=before_msg.created_at)
            except ChatMessage.DoesNotExist:
                pass

        return queryset.order_by('-created_at')[:limit]

    @classmethod
    def get_communication_reports(cls, academy=None) -> QuerySet[CommunicationReport]:
        """
        Retrieves communication reports for staff review.
        """
        queryset = CommunicationReport.objects.select_related(
            'reported_by', 'thread', 'reply', 'message', 'reviewed_by'
        )
        if academy:
            queryset = queryset.filter(
                Q(thread__isnull=False, thread__course__academy=academy) |
                Q(reply__isnull=False, reply__thread__course__academy=academy) |
                Q(message__isnull=False, message__room__academy=academy) |
                Q(reported_by__academy=academy)
            )
        return queryset.order_by('-created_at')
