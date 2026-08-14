from rest_framework import serializers
from discussions_chat.models import (
    DiscussionThread,
    DiscussionReply,
    DiscussionAttachment,
    ChatRoom,
    ChatParticipant,
    ChatMessage,
    ChatMessageAttachment,
    CommunicationReport,
)

#--------------------------------------------------------------
# 1. Discussion Attachment Model
#--------------------------------------------------------------

class DiscussionAttachmentSerializer(serializers.ModelSerializer):
    media_file_id = serializers.UUIDField(source='media_file.id', read_only=True)
    media_url = serializers.CharField(source='media_file.relative_path', read_only=True)
    original_name = serializers.CharField(source='media_file.original_filename', read_only=True)

    class Meta:
        model = DiscussionAttachment
        fields = ['id', 'media_file_id', 'media_url', 'original_name', 'order_index']

#--------------------------------------------------------------
# 2. Discussion Reply Model
#--------------------------------------------------------------

class DiscussionReplySerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(source='created_by.id', read_only=True)
    author_name = serializers.CharField(source='created_by.full_name', read_only=True)
    author_email = serializers.EmailField(source='created_by.email', read_only=True)
    attachments = DiscussionAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = DiscussionReply
        fields = [
            'id',
            'thread',
            'author_id',
            'author_name',
            'author_email',
            'parent_reply',
            'content',
            'is_answer',
            'is_pinned',
            'status',
            'attachments',
            'created_at',
            'edited_at',
        ]
        read_only_fields = ['id', 'is_answer', 'is_pinned', 'status', 'created_at']

#--------------------------------------------------------------
# 3. Discussion Thread Model
#--------------------------------------------------------------

class DiscussionThreadSerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(source='created_by.id', read_only=True)
    author_name = serializers.CharField(source='created_by.full_name', read_only=True)
    author_email = serializers.EmailField(source='created_by.email', read_only=True)
    attachments = DiscussionAttachmentSerializer(many=True, read_only=True)
    accepted_answer_id = serializers.UUIDField(source='accepted_answer.id', read_only=True)

    class Meta:
        model = DiscussionThread
        fields = [
            'id',
            'course',
            'author_id',
            'author_name',
            'author_email',
            'title',
            'content',
            'thread_type',
            'is_pinned',
            'is_locked',
            'status',
            'last_activity_at',
            'reply_count',
            'accepted_answer_id',
            'attachments',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'is_pinned',
            'is_locked',
            'status',
            'last_activity_at',
            'reply_count',
            'created_at',
        ]

#--------------------------------------------------------------
# 4. Discussion Thread Model
#--------------------------------------------------------------

class CreateThreadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    content = serializers.CharField()
    thread_type = serializers.CharField(required=False, default='DISCUSSION')
    media_file_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )

#--------------------------------------------------------------
# 4. Discussion Thread Model
#--------------------------------------------------------------

class CreateReplySerializer(serializers.Serializer):
    content = serializers.CharField()
    parent_reply_id = serializers.UUIDField(required=False, allow_null=True)
    media_file_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )

#--------------------------------------------------------------
# 5. Chat Message Attachment Model
#--------------------------------------------------------------

class ChatMessageAttachmentSerializer(serializers.ModelSerializer):
    media_file_id = serializers.UUIDField(source='media_file.id', read_only=True)
    media_url = serializers.CharField(source='media_file.relative_path', read_only=True)
    original_name = serializers.CharField(source='media_file.original_filename', read_only=True)

    class Meta:
        model = ChatMessageAttachment
        fields = ['id', 'media_file_id', 'media_url', 'original_name', 'attachment_type']

#--------------------------------------------------------------
# 6. Chat Message Model
#--------------------------------------------------------------

class ChatMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(source='sender.id', read_only=True)
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    attachments = ChatMessageAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ChatMessage
        fields = [
            'id',
            'room',
            'sender_id',
            'sender_name',
            'message_type',
            'content',
            'reply_to',
            'status',
            'attachments',
            'created_at',
            'edited_at',
        ]
        read_only_fields = fields

#--------------------------------------------------------------
# 7. Chat Room Model
#--------------------------------------------------------------

class ChatRoomSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    unread_count = serializers.IntegerField(default=0, read_only=True)

    class Meta:
        model = ChatRoom
        fields = [
            'id',
            'academy',
            'course',
            'course_title',
            'room_type',
            'name',
            'is_locked',
            'last_message_at',
            'unread_count',
            'created_at',
        ]
        read_only_fields = fields

#--------------------------------------------------------------
# 8. Communication Report Model
#--------------------------------------------------------------

class CommunicationReportSerializer(serializers.ModelSerializer):
    reported_by_email = serializers.EmailField(source='reported_by.email', read_only=True)

    class Meta:
        model = CommunicationReport
        fields = [
            'id',
            'reported_by_email',
            'thread',
            'reply',
            'message',
            'reason',
            'description',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

#--------------------------------------------------------------
# 9. Create Report Model
#--------------------------------------------------------------

class CreateReportSerializer(serializers.Serializer):
    thread_id = serializers.UUIDField(required=False, allow_null=True)
    reply_id = serializers.UUIDField(required=False, allow_null=True)
    message_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default='')
