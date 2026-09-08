from leads.models import (
    FollowUpType,
    InterestLevel,
    Lead,
    LeadActivity,
    LeadCourseInterest,
    LeadFollowUp,
    LeadImportJob,
    LeadNote,
    LeadStatus,
    LeadTag,
)
from rest_framework import serializers

# --------------------------------------------------------------
# 1. Lead Read Component Serializers
# --------------------------------------------------------------

class LeadCourseInterestSerializer(serializers.ModelSerializer):
    course_id = serializers.UUIDField(source='course.id', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = LeadCourseInterest
        fields = ['id', 'course_id', 'course_title', 'interest_level', 'is_primary']

class LeadTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadTag
        fields = ['id', 'name', 'color']

class LeadNoteSerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(source='author.id', read_only=True)
    author_name = serializers.CharField(source='author.full_name', read_only=True)

    class Meta:
        model = LeadNote
        fields = ['id', 'author_id', 'author_name', 'content', 'is_pinned', 'created_at']

class LeadFollowUpSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = LeadFollowUp
        fields = [
            'id',
            'follow_up_type',
            'scheduled_at',
            'completed_at',
            'status',
            'assigned_to_name',
            'outcome',
            'notes',
            'created_by_name',
            'created_at',
        ]

class LeadActivitySerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source='performed_by.full_name', read_only=True)

    class Meta:
        model = LeadActivity
        fields = ['id', 'activity_type', 'performed_by_name', 'occurred_at', 'metadata']

# --------------------------------------------------------------
# 2. Lead Main Read & Write Serializers
# Provides CRM representation for Academy Admin / Staff.
# --------------------------------------------------------------

class LeadSerializer(serializers.ModelSerializer):
    assigned_to_id = serializers.UUIDField(source='assigned_to.id', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True)
    converted_student_id = serializers.UUIDField(source='converted_student.id', read_only=True)
    course_interests = LeadCourseInterestSerializer(many=True, read_only=True)
    tags = LeadTagSerializer(many=True, read_only=True)
    notes = LeadNoteSerializer(many=True, read_only=True)
    follow_ups = LeadFollowUpSerializer(many=True, read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id',
            'full_name',
            'email',
            'phone',
            'status',
            'priority',
            'source',
            'source_detail',
            'preferred_contact_method',
            'assigned_to_id',
            'assigned_to_name',
            'assigned_to_email',
            'converted_student_id',
            'next_follow_up_at',
            'last_contacted_at',
            'converted_at',
            'lost_reason',
            'notes_summary',
            'course_interests',
            'tags',
            'notes',
            'follow_ups',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

class CreateLeadSerializer(serializers.ModelSerializer):
    course_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Lead
        fields = [
            'full_name',
            'email',
            'phone',
            'source',
            'source_detail',
            'priority',
            'preferred_contact_method',
            'course_id',
        ]

    def validate(self, attrs):
        # A Lead must provide at least one usable contact method.
        if not attrs.get('email') and not attrs.get('phone'):
            raise serializers.ValidationError("At least one contact method (email or phone) must be provided.")
        return attrs

class DemoLeadCreateSerializer(serializers.Serializer):
    academy_id = serializers.UUIDField(required=True)
    course_id = serializers.UUIDField(required=True)
    requested_date = serializers.DateField(required=False, allow_null=True)
    requested_time = serializers.CharField(required=False, allow_blank=True, default='')
    phone = serializers.CharField(required=False, allow_blank=True, default='')
    message = serializers.CharField(required=False, allow_blank=True, default='')

class DemoLeadResponseSerializer(serializers.ModelSerializer):
    academy = serializers.UUIDField(source='academy.id', read_only=True)
    course = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    requested_date = serializers.SerializerMethodField()
    requested_time = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id',
            'academy',
            'course',
            'student',
            'phone',
            'requested_date',
            'requested_time',
            'message',
            'status',
            'created_at',
        ]

    def get_course(self, obj):
        first_interest = obj.course_interests.first()
        if first_interest and first_interest.course:
            return {
                'id': str(first_interest.course.id),
                'title': first_interest.course.title,
            }
        return None

    def get_student(self, obj):
        return {
            'id': str(obj.converted_user.id) if obj.converted_user else None,
            'name': obj.full_name,
            'email': obj.email,
        }

    def get_requested_date(self, obj):
        return obj.metadata.get('requested_date', None)

    def get_requested_time(self, obj):
        return obj.metadata.get('requested_time', '')

    def get_message(self, obj):
        return obj.metadata.get('message', '')

class PublicLeadEnquirySerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    course_id = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, default='')

    # Marketing attribution tracking
    utm_source = serializers.CharField(required=False, allow_blank=True, default='')
    utm_medium = serializers.CharField(required=False, allow_blank=True, default='')
    utm_campaign = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        email = attrs.get('email', '')
        phone = attrs.get('phone', '')
        if not email and not phone:
            raise serializers.ValidationError("Either email or phone must be provided.")
        return attrs

# --------------------------------------------------------------
# 4. Action & Lifecycle Serializers
# --------------------------------------------------------------

class AssignLeadSerializer(serializers.Serializer):
    assigned_to_id = serializers.UUIDField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')

class TransitionStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=LeadStatus.choices)
    lost_reason = serializers.CharField(required=False, allow_blank=True, default='')

class ConvertLeadSerializer(serializers.Serializer):
    course_id = serializers.UUIDField(required=False, allow_null=True)
    create_enrollment = serializers.BooleanField(default=True)
    enrollment_access_type = serializers.CharField(default='FULL')

class ScheduleFollowUpSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField()
    follow_up_type = serializers.ChoiceField(choices=FollowUpType.choices, default=FollowUpType.CALL)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    assigned_to_id = serializers.UUIDField(required=False, allow_null=True)

class CompleteFollowUpSerializer(serializers.Serializer):
    outcome = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')

class CreateLeadNoteSerializer(serializers.Serializer):
    content = serializers.CharField()
    is_pinned = serializers.BooleanField(default=False)

class AddCourseInterestSerializer(serializers.Serializer):
    course_id = serializers.UUIDField()
    interest_level = serializers.ChoiceField(choices=InterestLevel.choices, default=InterestLevel.HIGH)

# --------------------------------------------------------------
# 5. Lead Import Job Serializer
# --------------------------------------------------------------

class LeadImportJobSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.EmailField(source='uploaded_by.email', read_only=True)

    class Meta:
        model = LeadImportJob
        fields = [
            'id',
            'status',
            'uploaded_by_email',
            'total_rows',
            'processed_rows',
            'created_count',
            'updated_count',
            'failed_count',
            'started_at',
            'completed_at',
            'created_at',
        ]
