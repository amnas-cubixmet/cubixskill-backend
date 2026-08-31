from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied

from storage.models import MediaFile
from enrollments.services import EnrollmentAccessService
from features.services import CourseFeatureService, StudentFeatureService
from notifications.services import EmailService
from discussions_chat.models import (
    DiscussionThread,
    DiscussionReply,
    DiscussionAttachment,
    ChatRoom,
    ChatParticipant,
    ChatMessage,
    ChatMessageAttachment,
    CommunicationReport,
    ThreadType,
    ThreadStatus,
    RoomType,
    MessageType,
    MessageStatus,
    ReportStatus,
)
#--------------------------------------------------------------
# 1. Discussion Service
#--------------------------------------------------------------
class DiscussionService:

    @classmethod
    @transaction.atomic
    def create_thread(
        cls,
        course,
        user,
        title: str,
        content: str,
        thread_type: str = 'DISCUSSION',
        media_file_ids: list[str] = None
    ) -> DiscussionThread:
        """
        Creates a new discussion thread in a course after validating feature activation and permissions.
        """
        academy = course.academy if course else getattr(user, 'academy', None)
        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and academy and user.academy == academy)

        # 1. Feature Activation Check
        if course and not is_staff:
            has_feature = StudentFeatureService.has_course_feature(user, course, 'course_discussions')
            if not has_feature:
                raise PermissionDenied("Discussions feature is disabled for this course or student has no access.")

        # 2. Announcement Restrictions (Only staff can post announcements)
        if thread_type == ThreadType.ANNOUNCEMENT and not is_staff:
            raise PermissionDenied("Only Academy staff can create announcement threads.")

        # 3. Create Thread
        thread = DiscussionThread.objects.create(
            academy=academy,
            course=course,
            created_by=user,
            title=title,
            content=content,
            thread_type=thread_type,
            last_activity_at=timezone.now()
        )

        # 4. Attach Media Files
        if media_file_ids:
            for idx, media_id in enumerate(media_file_ids):
                try:
                    media_file = MediaFile.objects.get(id=media_id)
                    DiscussionAttachment.objects.create(
                        thread=thread,
                        media_file=media_file,
                        uploaded_by=user,
                        order_index=idx
                    )
                except MediaFile.DoesNotExist:
                    pass

        return thread

    @classmethod
    def broadcast_event(cls, academy_id: str, event_type: str, data: dict):
        """
        Helper method to send real-time WebSocket events to an Academy channel group safely after DB commit.
        """
        import uuid
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        group_name = f'academy_discussions_{academy_id or "global"}'
        event_payload = {
            'type': 'discussion_event',
            'event_type': event_type,
            'event_id': str(uuid.uuid4()),
            'academy_id': str(academy_id) if academy_id else None,
            'occurred_at': timezone.now().isoformat(),
            'data': data
        }

        transaction.on_commit(lambda: async_to_sync(channel_layer.group_send)(group_name, event_payload))

    @classmethod
    @transaction.atomic
    def add_reply(
        cls,
        thread: DiscussionThread,
        user,
        content: str,
        parent_reply_id: str = None,
        media_file_ids: list[str] = None
    ) -> DiscussionReply:
        """
        Adds a reply to a discussion thread.
        """
        if thread.is_locked:
            raise ValidationError("This thread is locked for new replies.")
        if thread.status != ThreadStatus.ACTIVE:
            raise ValidationError("Cannot reply to a removed or moderated thread.")

        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and user.academy == thread.course.academy)
        if not is_staff:
            has_feature = StudentFeatureService.has_course_feature(user, thread.course, 'course_discussions')
            if not has_feature:
                raise PermissionDenied("Discussions feature is disabled for this course.")

        parent_reply = None
        if parent_reply_id:
            try:
                parent_reply = DiscussionReply.objects.get(id=parent_reply_id, thread=thread)
            except DiscussionReply.DoesNotExist:
                raise ValidationError("Parent reply not found.")

        reply = DiscussionReply.objects.create(
            thread=thread,
            created_by=user,
            parent_reply=parent_reply,
            content=content
        )

        # Update Thread Activity & Reply Count
        now = timezone.now()
        thread.reply_count += 1
        thread.last_activity_at = now
        thread.save(update_fields=['reply_count', 'last_activity_at'])

        # Attach Media Files
        if media_file_ids:
            for idx, media_id in enumerate(media_file_ids):
                try:
                    media_file = MediaFile.objects.get(id=media_id)
                    DiscussionAttachment.objects.create(
                        reply=reply,
                        media_file=media_file,
                        uploaded_by=user,
                        order_index=idx
                    )
                except MediaFile.DoesNotExist:
                    pass

        # Broadcast reply.created
        from discussions_chat.serializers import DiscussionReplySerializer
        academy_id = thread.academy.id if thread.academy else None
        cls.broadcast_event(
            academy_id=academy_id,
            event_type='reply.created',
            data={
                'discussion_id': str(thread.id),
                'reply': DiscussionReplySerializer(reply).data
            }
        )

        # Send Notification to Thread Author
        if thread.created_by and thread.created_by != user:
            EmailService.send_transactional(
                recipient=thread.created_by.email,
                template_code="DISCUSSION_REPLY_NOTIFICATION",
                subject=f"New reply on your thread: {thread.title}",
                context={
                    'body': f"{user.full_name or user.email} replied to your thread '{thread.title}'.",
                    'thread_title': thread.title,
                },
                user=thread.created_by,
                academy=thread.course.academy if thread.course else None
            )

        return reply

    @classmethod
    @transaction.atomic
    def mark_accepted_answer(cls, thread: DiscussionThread, reply: DiscussionReply, user) -> DiscussionThread:
        """
        Marks a reply as the accepted answer for a QUESTION thread.
        """
        if thread.thread_type != ThreadType.QUESTION:
            raise ValidationError("Accepted answers can only be set on Question threads.")

        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and user.academy == thread.course.academy)
        if thread.created_by != user and not is_staff:
            raise PermissionDenied("Only the thread author or staff can accept an answer.")

        if reply.thread != thread:
            raise ValidationError("Reply does not belong to this thread.")

        # Clear previous accepted answer if any
        DiscussionReply.objects.filter(thread=thread, is_answer=True).update(is_answer=False)

        reply.is_answer = True
        reply.save(update_fields=['is_answer'])

        thread.accepted_answer = reply
        thread.save(update_fields=['accepted_answer'])

        from discussions_chat.serializers import DiscussionThreadSerializer
        academy_id = thread.academy.id if thread.academy else None
        cls.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.answer_accepted',
            data=DiscussionThreadSerializer(thread).data
        )

        return thread

    @classmethod
    def toggle_pin_thread(cls, thread: DiscussionThread, staff_user, is_pinned: bool) -> DiscussionThread:
        thread.is_pinned = is_pinned
        thread.save(update_fields=['is_pinned'])

        from discussions_chat.serializers import DiscussionThreadSerializer
        academy_id = thread.academy.id if thread.academy else None
        cls.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.pinned' if is_pinned else 'discussion.unpinned',
            data=DiscussionThreadSerializer(thread).data
        )
        return thread

    @classmethod
    def toggle_lock_thread(cls, thread: DiscussionThread, staff_user, is_locked: bool) -> DiscussionThread:
        thread.is_locked = is_locked
        thread.save(update_fields=['is_locked'])

        from discussions_chat.serializers import DiscussionThreadSerializer
        academy_id = thread.academy.id if thread.academy else None
        cls.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.locked' if is_locked else 'discussion.unlocked',
            data=DiscussionThreadSerializer(thread).data
        )
        return thread

    @classmethod
    def soft_delete_thread(cls, thread: DiscussionThread, user) -> DiscussionThread:
        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and user.academy == thread.course.academy)
        if thread.created_by != user and not is_staff:
            raise PermissionDenied("You do not have permission to delete this thread.")

        thread.status = ThreadStatus.REMOVED
        thread.save(update_fields=['status'])

        academy_id = thread.academy.id if thread.academy else None
        cls.broadcast_event(
            academy_id=academy_id,
            event_type='discussion.deleted',
            data={'id': str(thread.id)}
        )
        return thread
        
#--------------------------------------------------------------
# 2. Chat Service
#--------------------------------------------------------------

class ChatService:

    @classmethod
    def get_or_create_course_chat_room(cls, course) -> ChatRoom:
        """
        Ensures a default ChatRoom exists for a Course.
        """
        room, _ = ChatRoom.objects.get_or_create(
            course=course,
            room_type=RoomType.COURSE,
            defaults={
                'academy': course.academy,
                'name': f"{course.title} Chat",
                'is_active': True
            }
        )
        return room

    @classmethod
    def validate_chat_access(cls, user, room: ChatRoom) -> bool:
        """
        Rigorous multi-tenant, enrollment, and feature verification for Chat access.
        """
        if not room.is_active or room.is_locked:
            return False

        # Staff bypass
        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and user.academy == room.academy)
        if is_staff:
            return True

        # Check blocked participant
        participant = ChatParticipant.objects.filter(room=room, user=user).first()
        if participant and participant.is_blocked:
            return False

        # If Course Room: Validate Course Feature & Student Enrollment
        if room.course:
            has_access, _, _ = EnrollmentAccessService.can_access_course(user, room.course)
            if not has_access:
                return False

            has_feature = CourseFeatureService.has_feature(room.course, 'COURSE_DISCUSSION')
            if not has_feature:
                return False

        return True

    @classmethod
    @transaction.atomic
    def send_message(
        cls,
        room: ChatRoom,
        user,
        content: str,
        message_type: str = 'TEXT',
        reply_to_id: str = None,
        media_file_ids: list[str] = None
    ) -> ChatMessage:
        """
        Creates and stores a chat message in PostgreSQL.
        """
        if not cls.validate_chat_access(user, room):
            raise PermissionDenied("Chat is disabled for this course or student has no access.")

        # Backend check for DIRECT / Personal chat file uploads
        if media_file_ids and room.room_type == RoomType.DIRECT:
            academy = room.academy or getattr(user, 'academy', None)
            if academy and not getattr(academy, 'personal_chat_file_upload_enabled', True):
                from core.utils import CubixSkillAPIException
                raise CubixSkillAPIException(
                    "File uploads are disabled for personal chat.",
                    code="CHAT_FILE_UPLOAD_DISABLED",
                    status_code=403
                )

        # Backend check for COURSE / Community chat file uploads
        if media_file_ids and room.room_type == RoomType.COURSE:
            academy = room.academy or getattr(user, 'academy', None)
            if academy and not getattr(academy, 'community_chat_file_upload_enabled', True):
                from core.utils import CubixSkillAPIException
                raise CubixSkillAPIException(
                    "File uploads are disabled for community chat.",
                    code="COMMUNITY_CHAT_FILE_UPLOAD_DISABLED",
                    status_code=403
                )

        participant, _ = ChatParticipant.objects.get_or_create(
            room=room,
            user=user
        )

        if participant.is_muted:
            raise PermissionDenied("You are muted in this chat room.")

        reply_to = None
        if reply_to_id:
            try:
                reply_to = ChatMessage.objects.get(id=reply_to_id, room=room)
            except ChatMessage.DoesNotExist:
                pass

        message = ChatMessage.objects.create(
            room=room,
            sender=user,
            content=content,
            message_type=message_type,
            reply_to=reply_to
        )

        # Update Room Last Activity
        now = timezone.now()
        room.last_message_at = now
        room.save(update_fields=['last_message_at'])

        # Attachments
        if media_file_ids:
            for idx, media_id in enumerate(media_file_ids):
                try:
                    media_file = MediaFile.objects.get(id=media_id)
                    ChatMessageAttachment.objects.create(
                        message=message,
                        media_file=media_file,
                        order_index=idx
                    )
                except MediaFile.DoesNotExist:
                    pass

        # Update sender read marker
        participant.last_read_message = message
        participant.last_read_at = now
        participant.save(update_fields=['last_read_message', 'last_read_at'])

        return message

    @classmethod
    def mark_room_as_read(cls, room: ChatRoom, user) -> int:
        """
        Marks room as read up to the latest message and returns remaining unread count (0).
        """
        latest_message = ChatMessage.objects.filter(room=room, status=MessageStatus.ACTIVE).order_by('-created_at').first()
        now = timezone.now()

        participant, _ = ChatParticipant.objects.get_or_create(
            room=room,
            user=user
        )
        participant.last_read_message = latest_message
        participant.last_read_at = now
        participant.save(update_fields=['last_read_message', 'last_read_at'])

        return 0

    @classmethod
    def get_unread_count(cls, room: ChatRoom, user) -> int:
        """
        Calculates unread message count efficiently for a user in a room.
        """
        participant = ChatParticipant.objects.filter(room=room, user=user).first()
        if not participant or not participant.last_read_at:
            return ChatMessage.objects.filter(room=room, status=MessageStatus.ACTIVE).exclude(sender=user).count()

        return ChatMessage.objects.filter(
            room=room,
            status=MessageStatus.ACTIVE,
            created_at__gt=participant.last_read_at
        ).exclude(sender=user).count()

    @classmethod
    @transaction.atomic
    def get_or_create_personal_room(cls, course, student, staff_user) -> ChatRoom:
        """
        Gets or creates a private 1-on-1 ChatRoom between a student and academy staff for a course.
        Validates tenant and student enrollment. Identifies student vs staff dynamically if caller is student.
        """
        # 1. Determine student vs staff roles dynamically
        target_student = student
        target_staff = staff_user

        # If student param is actually staff, or staff_user is not staff but student is student:
        is_student_staff = getattr(student, 'is_staff', False) or (hasattr(student, 'academy') and course.academy and student.academy == course.academy)
        is_staff_staff = getattr(staff_user, 'is_staff', False) or (hasattr(staff_user, 'academy') and course.academy and staff_user.academy == course.academy)

        if not is_staff_staff and is_student_staff:
            target_student, target_staff = staff_user, student
        elif not is_staff_staff and not is_student_staff:
            # Caller is student, student param passed is student.
            # Resolve default academy staff (e.g. course instructor or academy owner) as staff participant
            target_student = student if not is_student_staff else staff_user
            target_staff = course.instructor if course.instructor else course.academy.owner if hasattr(course.academy, 'owner') else None
            if not target_staff:
                from users_roles.models import User
                target_staff = User.objects.filter(academy=course.academy, is_staff=True).first() or User.objects.filter(is_superuser=True).first()

        if getattr(target_staff, 'academy', None) and course.academy != target_staff.academy and not getattr(target_staff, 'is_staff', False):
            raise PermissionDenied("Course does not belong to your Academy.")

        has_access, _, _ = EnrollmentAccessService.can_access_course(target_student, course)
        if not has_access and not getattr(target_student, 'is_staff', False):
            raise ValidationError({"student_id": "Student is not enrolled in this course."})

        # Look for existing DIRECT chat room for this course and student
        existing_rooms = ChatRoom.objects.filter(
            course=course,
            room_type=RoomType.DIRECT,
            is_active=True,
            participants__user=target_student
        ).distinct()

        if existing_rooms.exists():
            room = existing_rooms.first()
            if target_staff and not ChatParticipant.objects.filter(room=room, user=target_staff).exists():
                ChatParticipant.objects.get_or_create(room=room, user=target_staff)
        else:
            room = ChatRoom.objects.create(
                academy=course.academy,
                course=course,
                room_type=RoomType.DIRECT,
                name=f"Private DM: {target_student.full_name or target_student.email}",
                created_by=target_staff or target_student,
                is_active=True,
                last_message_at=timezone.now()
            )

        # Ensure participants exist
        ChatParticipant.objects.get_or_create(room=room, user=target_student)
        if target_staff:
            ChatParticipant.objects.get_or_create(room=room, user=target_staff)

        return room

    @classmethod
    @transaction.atomic
    def get_or_create_community_room(cls, course, user) -> ChatRoom:
        """
        Gets or creates an automatic WhatsApp-style Community Group ChatRoom for a course.
        Validates tenant access and automatically populates participant membership.
        """
        user_academy = getattr(user, 'academy', None)
        if user_academy and course.academy != user_academy and not getattr(user, 'is_staff', False):
            raise PermissionDenied("Course does not belong to your Academy.")

        if not CourseFeatureService.has_feature(course, 'COURSE_DISCUSSION'):
            raise PermissionDenied("Community discussion feature is disabled for this course.")

        existing_room = ChatRoom.objects.filter(
            course=course,
            room_type=RoomType.COURSE,
            is_active=True
        ).first()

        if existing_room:
            room = existing_room
        else:
            room, _ = ChatRoom.objects.get_or_create(
                course=course,
                room_type=RoomType.COURSE,
                defaults={
                    'academy': course.academy,
                    'name': f"{course.title} — Community Group",
                    'created_by': user,
                    'is_active': True,
                    'last_message_at': timezone.now()
                }
            )

        # Ensure participant membership
        ChatParticipant.objects.get_or_create(room=room, user=user)
        return room

    @classmethod
    def create_report(
        cls,
        user,
        reason: str,
        thread=None,
        reply=None,
        message=None,
        description: str = ""
    ) -> CommunicationReport:
        targets = [t for t in [thread, reply, message] if t is not None]
        if len(targets) != 1:
            raise ValidationError("Report must reference exactly one target (thread, reply, or message).")

        return CommunicationReport.objects.create(
            reported_by=user,
            thread=thread,
            reply=reply,
            message=message,
            reason=reason,
            description=description,
            status=ReportStatus.OPEN
        )
