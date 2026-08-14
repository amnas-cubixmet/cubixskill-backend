from django.db import models
from django.utils import timezone
from core.models import BaseModel, ActiveMixin

class ThreadType(models.TextChoices):
    DISCUSSION = 'DISCUSSION', 'Discussion'
    QUESTION = 'QUESTION', 'Question'
    ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'

class ThreadStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    REMOVED = 'REMOVED', 'Removed'
    MODERATED = 'MODERATED', 'Moderated'

class RoomType(models.TextChoices):
    COURSE = 'COURSE', 'Course Chat'
    DIRECT = 'DIRECT', 'Direct Chat'
    LIVE_SESSION = 'LIVE_SESSION', 'Live Session Chat'

class ParticipantRole(models.TextChoices):
    OWNER = 'OWNER', 'Owner'
    MODERATOR = 'MODERATOR', 'Moderator'
    MEMBER = 'MEMBER', 'Member'

class MessageType(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
    FILE = 'FILE', 'File'
    SYSTEM = 'SYSTEM', 'System'

class MessageStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    DELETED = 'DELETED', 'Deleted'
    MODERATED = 'MODERATED', 'Moderated'

class ReportStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    REVIEWING = 'REVIEWING', 'Reviewing'
    RESOLVED = 'RESOLVED', 'Resolved'
    DISMISSED = 'DISMISSED', 'Dismissed'

#--------------------------------------------------------------
# 1. Discussion Thread Model
#--------------------------------------------------------------

class DiscussionThread(BaseModel, ActiveMixin):
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='discussion_threads',
        null=True,
        blank=True
    )
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='discussion_threads',
        null=True,
        blank=True
    )

    title = models.CharField(max_length=255)
    content = models.TextField()
    thread_type = models.CharField(
        max_length=20,
        choices=ThreadType.choices,
        default=ThreadType.DISCUSSION
    )

    is_pinned = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ThreadStatus.choices,
        default=ThreadStatus.ACTIVE,
        db_index=True
    )

    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    reply_count = models.PositiveIntegerField(default=0)

    accepted_answer = models.ForeignKey(
        'DiscussionReply',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'discussion_threads'
        ordering = ['-is_pinned', '-last_activity_at']

    def __str__(self):
        return f"[{self.thread_type}] {self.title}"

#--------------------------------------------------------------
# 2. Discussion Reply Model
#--------------------------------------------------------------

class DiscussionReply(BaseModel, ActiveMixin):
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        related_name='replies',
        null=True,
        blank=True
    )
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='discussion_replies',
        null=True,
        blank=True
    )
    parent_reply = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='child_replies'
    )
    content = models.TextField()
    is_answer = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ThreadStatus.choices,
        default=ThreadStatus.ACTIVE
    )
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'discussion_replies'
        ordering = ['created_at']

    def __str__(self):
        return f"Reply by {self.created_by} on {self.thread.title}"

#--------------------------------------------------------------
# 3. Discussion Attachment Model
#--------------------------------------------------------------

class DiscussionAttachment(BaseModel):
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments'
    )
    reply = models.ForeignKey(
        DiscussionReply,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments'
    )
    media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.CASCADE,
        related_name='+'
    )
    uploaded_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='+'
    )
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'discussion_attachments'
        ordering = ['order_index']

    def __str__(self):
        return f"Attachment {self.media_file.original_name}"

#--------------------------------------------------------------
# 4. Chat Room Model
#--------------------------------------------------------------

class ChatRoom(BaseModel, ActiveMixin):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='chat_rooms',
        null=True,
        blank=True
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chat_rooms'
    )
    room_type = models.CharField(
        max_length=20,
        choices=RoomType.choices,
        default=RoomType.COURSE
    )
    name = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    is_locked = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'chat_rooms'
        ordering = ['-last_message_at']

    def __str__(self):
        return f"ChatRoom '{self.name or self.course.title}' ({self.room_type})"

#--------------------------------------------------------------
# 5. Chat Participant Model
#--------------------------------------------------------------

class ChatParticipant(BaseModel):
    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='participants',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='chat_participations'
    )
    role = models.CharField(
        max_length=20,
        choices=ParticipantRole.choices,
        default=ParticipantRole.MEMBER
    )
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    is_muted = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)

    last_read_message = models.ForeignKey(
        'ChatMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_participants'
        unique_together = ('room', 'user')

    def __str__(self):
        return f"{self.user.email} in {self.room.name}"

#--------------------------------------------------------------
# 6. Chat Message Model
#--------------------------------------------------------------

class ChatMessage(BaseModel):
    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='messages',
        null=True,
        blank=True
    )
    sender = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='sent_chat_messages',
        null=True,
        blank=True
    )
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT
    )
    content = models.TextField(blank=True, default='')
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies'
    )
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=MessageStatus.choices,
        default=MessageStatus.ACTIVE
    )

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"Message by {self.sender} in {self.room}"

#--------------------------------------------------------------
# 7. Chat Message Attachment Model
#--------------------------------------------------------------

class ChatMessageAttachment(BaseModel):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='attachments',
        null=True,
        blank=True
    )
    media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.CASCADE,
        related_name='+'
    )
    attachment_type = models.CharField(max_length=30, default='FILE')
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'chat_message_attachments'
        ordering = ['order_index']

    def __str__(self):
        return f"Attachment {self.media_file.original_name} for message {self.message_id}"

#--------------------------------------------------------------
# 8. Chat Message Receipt Model
#--------------------------------------------------------------

class ChatMessageReceipt(BaseModel):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='receipts',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='+'
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'chat_message_receipts'
        unique_together = ('message', 'user')

    def __str__(self):
        return f"Receipt for {self.user.email} on msg {self.message_id}"

#--------------------------------------------------------------
# 9. Communication Report Model
#--------------------------------------------------------------

class CommunicationReport(BaseModel):
    reported_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='submitted_communication_reports'
    )
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    reply = models.ForeignKey(
        DiscussionReply,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    reason = models.TextField()
    description = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=ReportStatus.choices,
        default=ReportStatus.OPEN,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'communication_reports'
        ordering = ['-created_at']

    def __str__(self):
        return f"Report {self.id} by {self.reported_by.email} ({self.status})"
