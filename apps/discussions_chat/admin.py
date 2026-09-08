from discussions_chat.models import (
    ChatMessage,
    ChatParticipant,
    ChatRoom,
    CommunicationReport,
    DiscussionAttachment,
    DiscussionReply,
    DiscussionThread,
)
from django.contrib import admin

#--------------------------------------------------------------
# 1. Discussion Attachment Inline
#--------------------------------------------------------------

class DiscussionAttachmentInline(admin.TabularInline):
    model = DiscussionAttachment
    extra = 0

#--------------------------------------------------------------
# 2. Discussion Reply Inline
#--------------------------------------------------------------

class DiscussionReplyInline(admin.TabularInline):
    model = DiscussionReply
    extra = 0

@admin.register(DiscussionThread)
class DiscussionThreadAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'thread_type', 'status', 'is_pinned', 'is_locked', 'created_by', 'last_activity_at')
    list_filter = ('thread_type', 'status', 'is_pinned', 'is_locked', 'course')
    search_fields = ('title', 'content', 'created_by__email')
    inlines = [DiscussionReplyInline, DiscussionAttachmentInline]

@admin.register(DiscussionReply)
class DiscussionReplyAdmin(admin.ModelAdmin):
    list_display = ('thread', 'created_by', 'is_answer', 'status', 'created_at')
    list_filter = ('is_answer', 'status')
    search_fields = ('content', 'created_by__email', 'thread__title')

class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 0

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'room_type', 'course', 'academy', 'is_locked', 'last_message_at')
    list_filter = ('room_type', 'is_locked', 'academy')
    search_fields = ('name', 'course__title')
    inlines = [ChatParticipantInline]

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'sender', 'message_type', 'status', 'created_at')
    list_filter = ('message_type', 'status')
    search_fields = ('content', 'sender__email')

@admin.register(CommunicationReport)
class CommunicationReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reported_by', 'reason', 'status', 'created_at', 'reviewed_by')
    list_filter = ('status', 'created_at')
    search_fields = ('reason', 'description', 'reported_by__email')
