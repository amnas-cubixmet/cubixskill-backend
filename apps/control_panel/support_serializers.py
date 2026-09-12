import uuid
from rest_framework import serializers
from django.contrib.auth import get_user_model
from control_panel.models import SupportTicket, TicketMessage, TicketAttachment, TicketStatus, TicketPriority
from storage.models import MediaFile

User = get_user_model()


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = ['id', 'file_name', 'file_url', 'file_size', 'created_at']


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_email = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            'id',
            'ticket_id',
            'sender_id',
            'sender_name',
            'sender_email',
            'role',
            'is_internal_note',
            'message',
            'attachments',
            'created_at',
        ]

    def get_sender_name(self, obj):
        if not obj.sender:
            return "Unknown"
        name = getattr(obj.sender, 'full_name', '').strip()
        return name if name else obj.sender.email

    def get_sender_email(self, obj):
        return obj.sender.email if obj.sender else ""

    def get_role(self, obj):
        if not obj.sender:
            return "customer"
        if obj.sender.is_superuser or obj.sender.is_staff:
            return "support"
        return "customer"


class SupportTicketListSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    academy_name = serializers.SerializerMethodField()
    last_updated_human = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            'id',
            'ticket_number',
            'subject',
            'category',
            'priority',
            'status',
            'user_id',
            'user_name',
            'user_email',
            'academy_id',
            'academy_name',
            'created_at',
            'updated_at',
            'last_updated_human',
        ]

    def get_user_name(self, obj):
        if not obj.user:
            return "Unknown"
        name = getattr(obj.user, 'full_name', '').strip()
        return name if name else obj.user.email

    def get_user_email(self, obj):
        return obj.user.email if obj.user else ""

    def get_academy_name(self, obj):
        return obj.academy.name if obj.academy else "Central / Platform"

    def get_last_updated_human(self, obj):
        return obj.updated_at.strftime("%b %d, %Y • %I:%M %p")


class SupportTicketDetailSerializer(SupportTicketListSerializer):
    description = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta(SupportTicketListSerializer.Meta):
        fields = SupportTicketListSerializer.Meta.fields + [
            'description',
            'replies',
            'attachments',
            'assigned_to_id',
            'assigned_to_name',
        ]

    def get_description(self, obj):
        first_msg = obj.messages.filter(is_internal_note=False).order_by('created_at').first()
        return first_msg.message if first_msg else ""

    def get_replies(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        messages_qs = obj.messages.all()
        # Exclude internal notes for non-superadmin/central support users
        if not (user and (user.is_superuser or getattr(user, 'is_central_support', False))):
            messages_qs = messages_qs.filter(is_internal_note=False)
        return TicketMessageSerializer(messages_qs, many=True, context=self.context).data

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to:
            return None
        name = getattr(obj.assigned_to, 'full_name', '').strip()
        return name if name else obj.assigned_to.email


class SupportTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=50, default='GENERAL')
    priority = serializers.ChoiceField(choices=TicketPriority.choices, default=TicketPriority.MEDIUM)
    description = serializers.CharField(style={'base_template': 'textarea.html'})
    attachment_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    def validate_subject(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Subject cannot be empty.")
        return value.strip()

    def validate_description(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Description cannot be empty.")
        return value.strip()


class TicketReplyCreateSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_internal_note = serializers.BooleanField(default=False, required=False)
    attachment_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    def validate_message(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Message content cannot be empty.")
        return value.strip()
