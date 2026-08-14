from rest_framework import serializers
from users_roles.models import User
from courses.models import Course
from enrollments.models import (
    Enrollment,
    EnrollmentAccessPeriod,
    EnrollmentEvent,
    AccessType,
    EnrollmentStatus,
    EnrollmentSource
)

#--------------------------------------------------------------
# Student Minimal Serializer
#--------------------------------------------------------------

class StudentMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'phone']

#--------------------------------------------------------------
# Course Minimal Serializer
#--------------------------------------------------------------

class CourseMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['id', 'title', 'price', 'academy_id']

#--------------------------------------------------------------
# Enrollment Access Period Serializer
#--------------------------------------------------------------

class EnrollmentAccessPeriodSerializer(serializers.ModelSerializer):
    granted_by_name = serializers.CharField(source='granted_by.full_name', read_only=True, default='')

    class Meta:
        model = EnrollmentAccessPeriod
        fields = ['id', 'access_type', 'starts_at', 'expires_at', 'reason', 'granted_by', 'granted_by_name', 'source_reference', 'created_at']

#--------------------------------------------------------------
# Enrollment Event Serializer
#--------------------------------------------------------------

class EnrollmentEventSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source='performed_by.full_name', read_only=True, default='')

    class Meta:
        model = EnrollmentEvent
        fields = ['id', 'event_type', 'previous_status', 'new_status', 'occurred_at', 'performed_by', 'performed_by_name', 'reason', 'metadata']

class EnrollmentSerializer(serializers.ModelSerializer):
    student = StudentMinimalSerializer(read_only=True)
    course = CourseMinimalSerializer(read_only=True)
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            'id', 'student', 'course', 'access_type', 'status', 'source',
            'enrolled_at', 'access_starts_at', 'access_expires_at', 'is_lifetime',
            'source_reference', 'progress_percent', 'is_valid', 'created_at', 'updated_at'
        ]

    def get_is_valid(self, obj) -> bool:
        return obj.is_currently_valid()

#--------------------------------------------------------------
# Enrollment Detail Serializer
#--------------------------------------------------------------

class EnrollmentDetailSerializer(EnrollmentSerializer):
    access_periods = EnrollmentAccessPeriodSerializer(many=True, read_only=True)
    events = EnrollmentEventSerializer(many=True, read_only=True)

    class Meta(EnrollmentSerializer.Meta):
        fields = EnrollmentSerializer.Meta.fields + ['access_periods', 'events']

#--------------------------------------------------------------
# Create Enrollment Serializer
#--------------------------------------------------------------

class CreateEnrollmentSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    course_id = serializers.UUIDField()
    access_type = serializers.ChoiceField(choices=AccessType.choices, default=AccessType.FULL)
    source = serializers.ChoiceField(choices=EnrollmentSource.choices, default=EnrollmentSource.MANUAL)
    is_lifetime = serializers.BooleanField(default=True)
    access_expires_at = serializers.DateTimeField(required=False, allow_null=True)
    source_reference = serializers.CharField(required=False, allow_blank=True, default='')

#--------------------------------------------------------------
# Bulk Enrollment Serializer
#--------------------------------------------------------------

class BulkEnrollmentSerializer(serializers.Serializer):
    student_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    course_id = serializers.UUIDField()
    access_type = serializers.ChoiceField(choices=AccessType.choices, default=AccessType.FULL)
    is_lifetime = serializers.BooleanField(default=True)
    access_expires_at = serializers.DateTimeField(required=False, allow_null=True)

#--------------------------------------------------------------
# Extend Enrollment Serializer
#--------------------------------------------------------------

class ExtendEnrollmentSerializer(serializers.Serializer):
    additional_days = serializers.IntegerField(required=False, min_value=1)
    new_expiry_date = serializers.DateTimeField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if not attrs.get('additional_days') and not attrs.get('new_expiry_date'):
            raise serializers.ValidationError("Either additional_days or new_expiry_date must be provided.")
        return attrs

#--------------------------------------------------------------
# Lifecycle Action Serializer
#--------------------------------------------------------------

class LifecycleActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')
