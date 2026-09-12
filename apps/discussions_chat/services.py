from discussions_chat.models import (
    ChatMessage,
    ChatMessageAttachment,
    ChatParticipant,
    ChatRoom,
    CommunicationReport,
    DiscussionAttachment,
    DiscussionReply,
    DiscussionThread,
    MessageStatus,
    ReportStatus,
    RoomType,
    ThreadStatus,
    ThreadType,
)
from django.db import transaction
from django.utils import timezone
from enrollments.services import EnrollmentAccessService
from features.services import CourseFeatureService, StudentFeatureService
from notifications.services import EmailService
from rest_framework.exceptions import PermissionDenied, ValidationError
from storage.models import MediaFile


#--------------------------------------------------------------
# 1. Discussion Service
#--------------------------------------------------------------
class DiscussionService:

    @classmethod
    def get_eligible_email_recipients(cls, course=None, academy=None):
        """
        Calculates eligible student email recipients for an announcement based on scope.
        Rules:
        - Must belong to the specified Academy
        - If course-specific, must be enrolled in the selected course and active
        - Must have a non-empty, valid email address
        - Unique email addresses only
        """
        from users_roles.models import User

        if course:
            target_academy = course.academy
            students_qs = User.objects.filter(
                enrollments__course=course,
                enrollments__status__in=['ACTIVE', 'COMPLETED', 'ENROLLED']
            )
        elif academy:
            target_academy = academy
            students_qs = User.objects.filter(academy=academy)
        else:
            return []

        # Filter active students with non-empty email
        emails = set()
        eligible_users = []
        for user in students_qs.select_related('academy').distinct():
            email = (user.email or '').strip().lower()
            if email and '@' in email and email not in emails:
                emails.add(email)
                eligible_users.append(user)

        return eligible_users

    @classmethod
    def calculate_announcement_cost(cls, course=None, academy=None, send_email: bool = False):
        """
        Calculates the dynamic announcement and email delivery credit cost from central Super Admin pricing settings.
        Returns Decimal breakdown and recipient list.
        """
        from decimal import Decimal

        from control_panel.models import PricingService
        from credits.services import CreditsService

        target_academy = course.academy if course else academy
        balance = CreditsService.get_balance(target_academy) if target_academy else Decimal('0.000000')

        # Read active prices from PricingService (Control Panel)
        announcement_rate = Decimal(str(PricingService.get_credit_cost('COURSE_ANNOUNCEMENT', default_cost=2)))
        email_unit_rate = Decimal(str(PricingService.get_credit_cost('EMAIL_DELIVERY', default_cost=1)))

        # Check EMAIL_DELIVERY course feature if course is specified
        if course:
            from features.services import CourseFeatureService
            if not CourseFeatureService.has_feature(course, 'EMAIL_DELIVERY'):
                send_email = False

        recipients = cls.get_eligible_email_recipients(course=course, academy=target_academy) if send_email else []
        recipient_count = len(recipients) if send_email else 0

        email_cost = (Decimal(str(recipient_count)) * email_unit_rate).quantize(Decimal('0.000001')) if send_email else Decimal('0.000000')
        total_cost = (announcement_rate + email_cost).quantize(Decimal('0.000001'))

        has_sufficient = balance >= total_cost

        return {
            'announcement_price': str(announcement_rate.quantize(Decimal('0.000001'))),
            'email_enabled': send_email,
            'email_recipient_count': recipient_count,
            'email_unit_price': str(email_unit_rate.quantize(Decimal('0.000001'))),
            'email_cost': str(email_cost.quantize(Decimal('0.000001'))),
            'total_cost': str(total_cost.quantize(Decimal('0.000001'))),
            'academy_credit_balance': str(balance.quantize(Decimal('0.000001'))),
            'has_sufficient_credits': has_sufficient,
            'recipients': recipients,
            'announcement_rate_dec': announcement_rate,
            'email_cost_dec': email_cost,
            'total_cost_dec': total_cost,
        }

    @classmethod
    @transaction.atomic
    def create_thread(
        cls,
        course,
        user,
        title: str,
        content: str,
        thread_type: str = 'DISCUSSION',
        media_file_ids: list[str] = None,
        send_email: bool = False,
        publish_option: str = 'now'
    ) -> DiscussionThread:
        """
        Creates a new discussion thread or announcement in a course after validating permissions & executing credit billing.
        """
        from decimal import Decimal

        from core.exceptions import CubixSkillAPIException
        from credits.models import CreditAccount, CreditSourceType
        from credits.services import CreditsService

        academy = course.academy if course else getattr(user, 'academy', None)
        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and academy and user.academy == academy)

        # 1. Feature Activation Check
        if course:
            from features.services import CourseFeatureService
            if thread_type == ThreadType.ANNOUNCEMENT:
                CourseFeatureService.require_enabled(course, 'COURSE_ANNOUNCEMENT', user=user)
            else:
                CourseFeatureService.require_enabled(course, 'COURSE_DISCUSSION', user=user)

        # 2. Announcement Restrictions (Only staff can post announcements)
        if thread_type == ThreadType.ANNOUNCEMENT and not is_staff:
            raise PermissionDenied("Only Academy staff can create announcement threads.")

        is_announcement = (thread_type == ThreadType.ANNOUNCEMENT)
        is_draft = (publish_option == 'draft')
        is_publishing = is_announcement and not is_draft

        announcement_cost = Decimal('0.000000')
        email_cost = Decimal('0.000000')
        recipient_count = 0
        recipients_list = []

        if is_publishing and academy:
            # Recalculate cost dynamically on backend
            cost_info = cls.calculate_announcement_cost(course=course, academy=academy, send_email=send_email)
            total_required = cost_info['total_cost_dec']
            announcement_cost = cost_info['announcement_rate_dec']
            email_cost = cost_info['email_cost_dec']
            recipient_count = cost_info['email_recipient_count']
            recipients_list = cost_info['recipients']

            # Lock credit account and check balance
            account = CreditAccount.objects.select_for_update().filter(academy=academy).first()
            current_balance = account.balance if account else Decimal('0.000000')

            if current_balance < total_required:
                raise CubixSkillAPIException(
                    f"Insufficient academy credits. Required: {total_required}, Available: {current_balance}",
                    code="INSUFFICIENT_CREDITS",
                    status_code=400
                )

        # 3. Create Thread
        thread = DiscussionThread.objects.create(
            academy=academy,
            course=course,
            created_by=user,
            title=title,
            content=content,
            thread_type=thread_type,
            status=ThreadStatus.ACTIVE if not is_draft else ThreadStatus.REMOVED, # or draft representation
            send_email=send_email if is_announcement else False,
            email_recipient_count=recipient_count,
            email_status='PENDING' if (is_publishing and send_email and recipient_count > 0) else 'NOT_SENT',
            is_published=not is_draft,
            published_at=timezone.now() if not is_draft else None,
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

        # 5. Deduct Credits & Create Separate Ledger Entries for Announcement & Email Delivery
        if is_publishing and academy:
            # Entry 1: COURSE_ANNOUNCEMENT
            announcement_key = f"ANNOUNCEMENT_PUB:{thread.id}"
            CreditsService.debit(
                academy=academy,
                amount=announcement_cost,
                source_type=CreditSourceType.DAILY_USAGE, # or appropriate source type
                idempotency_key=announcement_key,
                description=f"Course Announcement Published: {title}",
                reference_type="ANNOUNCEMENT",
                reference_id=str(thread.id),
                created_by=user
            )
            thread.announcement_credits_charged = announcement_cost

            # Entry 2: EMAIL_DELIVERY (only if send_email is ON and recipient_count > 0)
            if send_email and recipient_count > 0:
                email_key = f"ANNOUNCEMENT_EMAIL:{thread.id}"
                CreditsService.debit(
                    academy=academy,
                    amount=email_cost,
                    source_type=CreditSourceType.EMAIL_USAGE,
                    idempotency_key=email_key,
                    description=f"Announcement Email Delivery ({recipient_count} recipients): {title}",
                    reference_type="ANNOUNCEMENT_EMAIL",
                    reference_id=str(thread.id),
                    created_by=user
                )
                thread.email_credits_charged = email_cost
                
                # Queue/dispatch emails using existing email service
                cls._dispatch_announcement_emails(thread, recipients_list)

            thread.credit_charge_applied = True
            thread.save(update_fields=['announcement_credits_charged', 'email_credits_charged', 'credit_charge_applied', 'email_status'])

        # 6. Dispatch In-App Notifications for Published Announcement
        if is_publishing:
            cls._dispatch_announcement_in_app_notifications(thread, recipients_list)

        return thread

    @classmethod
    def _dispatch_announcement_emails(cls, thread: DiscussionThread, recipients: list):
        """
        Dispatches announcement emails to eligible student recipients using existing EmailService infrastructure.
        """
        try:
            course_title = thread.course.title if thread.course else "Academy Update"
            subject = f"[{course_title}] {thread.title}"
            body = f"Announcement from {thread.academy.name if thread.academy else 'your instructor'}:\n\n{thread.content}"
            
            for recipient in recipients:
                EmailService.send_email(
                    to_email=recipient.email,
                    subject=subject,
                    body=body,
                    template_name="announcement_notification",
                    context={
                        "announcement_title": thread.title,
                        "announcement_content": thread.content,
                        "course_title": course_title,
                        "academy_name": thread.academy.name if thread.academy else ""
                    }
                )
            thread.email_status = 'SENT'
            thread.save(update_fields=['email_status'])
        except Exception as err:
            import logging
            logging.getLogger(__name__).error(f"Error dispatching announcement emails for thread {thread.id}: {err}")
            thread.email_status = 'FAILED'
            thread.save(update_fields=['email_status'])

    @classmethod
    def _dispatch_announcement_in_app_notifications(cls, thread: DiscussionThread, recipients: list):
        """
        Dispatches in-app notifications for published announcements to eligible recipients.
        Ensures idempotency using source_type='ANNOUNCEMENT' and source_id=str(thread.id).
        """
        from notifications.models import NotificationType
        from notifications.services import NotificationService

        academy_uuid = str(thread.academy.id) if thread.academy else ""
        course_uuid = str(thread.course.uuid) if (thread.course and hasattr(thread.course, 'uuid')) else (str(thread.course.id) if thread.course else "")
        
        if course_uuid and academy_uuid:
            action_url = f"/student/academies/{academy_uuid}/courses/{course_uuid}/announcements"
        elif academy_uuid:
            action_url = f"/student/academies/{academy_uuid}"
        else:
            action_url = "/student/academies"

        for recipient in recipients:
            try:
                NotificationService.notify_user(
                    recipient=recipient,
                    notification_type=NotificationType.ANNOUNCEMENT_PUBLISHED,
                    title=f"Announcement: {thread.title}",
                    message=thread.content[:200] + ("..." if len(thread.content) > 200 else ""),
                    action_type="NAVIGATE",
                    action_url=action_url,
                    source_type="ANNOUNCEMENT",
                    source_id=str(thread.id),
                    academy=thread.academy
                )
            except Exception as err:
                import logging
                logging.getLogger(__name__).error(f"Error creating notification for user {recipient.id}: {err}")

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

        if room.course:
            has_feature = CourseFeatureService.has_feature(room.course, 'COURSE_DISCUSSION')
            if not has_feature:
                return False

        # Staff bypass after feature check
        is_staff = getattr(user, 'is_staff', False) or (hasattr(user, 'academy') and user.academy == room.academy)
        if is_staff:
            return True

        # Check blocked participant
        participant = ChatParticipant.objects.filter(room=room, user=user).first()
        if participant and participant.is_blocked:
            return False

        # If Course Room: Validate Student Enrollment
        if room.course:
            has_access, _, _ = EnrollmentAccessService.can_access_course(user, room.course)
            if not has_access:
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
        Marks room as read up to the latest message, creates ChatMessageReceipt for unread messages,
        and returns remaining unread count (0).
        """
        latest_message = ChatMessage.objects.filter(room=room, status=MessageStatus.ACTIVE).order_by('-created_at').first()
        now = timezone.now()

        # Find messages not authored by user that need read receipt
        unread_messages = ChatMessage.objects.filter(
            room=room,
            status=MessageStatus.ACTIVE
        ).exclude(sender=user)

        from discussions_chat.models import ChatMessageReceipt
        for msg in unread_messages:
            receipt, created = ChatMessageReceipt.objects.get_or_create(
                message=msg,
                user=user,
                defaults={'delivered_at': now, 'read_at': now}
            )
            if not created and not receipt.read_at:
                receipt.read_at = now
                if not receipt.delivered_at:
                    receipt.delivered_at = now
                receipt.save(update_fields=['read_at', 'delivered_at'])

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
