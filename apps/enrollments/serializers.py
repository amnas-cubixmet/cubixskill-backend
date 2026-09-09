from courses.models import Course
from enrollments.models import (
    AccessType,
    Enrollment,
    EnrollmentAccessPeriod,
    EnrollmentEvent,
    EnrollmentSource,
)
from rest_framework import serializers
from users_roles.models import User

#--------------------------------------------------------------
# Student Minimal Serializer
#--------------------------------------------------------------

class StudentMinimalSerializer(serializers.ModelSerializer):
    uuid = serializers.CharField(source='id', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'uuid', 'email', 'full_name', 'phone']

#--------------------------------------------------------------
# Course Minimal Serializer
#--------------------------------------------------------------

class CourseMinimalSerializer(serializers.ModelSerializer):
    uuid = serializers.CharField(source='id', read_only=True)

    class Meta:
        model = Course
        fields = ['id', 'uuid', 'title', 'price', 'academy_id']

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
    uuid = serializers.CharField(source='id', read_only=True)
    student = StudentMinimalSerializer(read_only=True)
    course = CourseMinimalSerializer(read_only=True)
    is_valid = serializers.SerializerMethodField()

    completed_lessons = serializers.SerializerMethodField()
    total_lessons = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    completed_lessons_count = serializers.SerializerMethodField()
    total_lessons_count = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            'id', 'uuid', 'student', 'course', 'access_type', 'status', 'source',
            'enrolled_at', 'access_starts_at', 'access_expires_at', 'is_lifetime',
            'source_reference', 'progress_percent', 'progress_percentage',
            'completed_lessons', 'total_lessons', 'completed_lessons_count',
            'total_lessons_count', 'is_valid', 'created_at', 'updated_at'
        ]

    def get_is_valid(self, obj) -> bool:
        return obj.is_currently_valid()

    def get_total_lessons(self, obj) -> int:
        if hasattr(obj, 'annotated_total_lessons'):
            return getattr(obj, 'annotated_total_lessons', 0)
        if not getattr(obj, 'course_id', None):
            return 0
        from lessons.models import Lesson
        return Lesson.objects.filter(
            module__course_id=obj.course_id,
            is_active=True,
            module__is_active=True
        ).count()

    def get_completed_lessons(self, obj) -> int:
        if hasattr(obj, 'annotated_completed_lessons'):
            return getattr(obj, 'annotated_completed_lessons', 0)
        if not getattr(obj, 'student_id', None) or not getattr(obj, 'course_id', None):
            return 0
        from learning_progress.models import LessonProgress, ProgressStatus
        return LessonProgress.objects.filter(
            student_id=obj.student_id,
            lesson__module__course_id=obj.course_id,
            status=ProgressStatus.COMPLETED,
            lesson__is_active=True,
            lesson__module__is_active=True
        ).values('lesson_id').distinct().count()

    def get_progress_percentage(self, obj) -> float:
        total = self.get_total_lessons(obj)
        completed = self.get_completed_lessons(obj)
        if total <= 0:
            return 0.0
        pct = (completed / total) * 100.0
        return round(min(100.0, max(0.0, pct)), 2)

    def get_completed_lessons_count(self, obj) -> int:
        return self.get_completed_lessons(obj)

    def get_total_lessons_count(self, obj) -> int:
        return self.get_total_lessons(obj)

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
