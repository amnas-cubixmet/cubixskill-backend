from rest_framework import serializers
from courses.models import Course, CourseCategory, CourseLanguage, CourseModule, CategoryAlias, CategoryMergeAudit
from storage.serializers import MediaFileSerializer


#--------------------------------------------------------------
# Language Serializer
#--------------------------------------------------------------

class CourseLanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseLanguage
        fields = ['id', 'name', 'code', 'slug', 'is_active', 'order_index', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']


#--------------------------------------------------------------
# Category & Alias Serializers
#--------------------------------------------------------------

class CategoryAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoryAlias
        fields = ['id', 'name', 'slug', 'canonical_category', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']

class CourseCategorySerializer(serializers.ModelSerializer):
    aliases = CategoryAliasSerializer(many=True, read_only=True)
    courses_count = serializers.SerializerMethodField()

    class Meta:
        model = CourseCategory
        fields = ['id', 'name', 'slug', 'description', 'order_index', 'is_active', 'aliases', 'courses_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'aliases', 'courses_count', 'created_at', 'updated_at']

    def get_courses_count(self, obj):
        return obj.courses.count()


class CategoryMergeSerializer(serializers.Serializer):
    source_category_id = serializers.UUIDField(required=True)
    target_category_id = serializers.UUIDField(required=True)

    def validate(self, attrs):
        if attrs['source_category_id'] == attrs['target_category_id']:
            raise serializers.ValidationError("Source and Target categories cannot be identical.")
        return attrs

class CategoryMergeAuditSerializer(serializers.ModelSerializer):
    merged_by_name = serializers.CharField(source='merged_by.full_name', read_only=True, default='')

    class Meta:
        model = CategoryMergeAudit
        fields = ['id', 'source_category_name', 'target_category', 'courses_reassigned_count', 'merged_by_name', 'merged_at']
        read_only_fields = ['id', 'merged_at']


#--------------------------------------------------------------
# Module Serializer
#--------------------------------------------------------------

class CourseModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseModule
        fields = ['id', 'course', 'title', 'description', 'order_index', 'is_active']
        read_only_fields = ['id']

#--------------------------------------------------------------
# Course List & Detail Serializers
#--------------------------------------------------------------

class CourseListSerializer(serializers.ModelSerializer):
    thumbnail = MediaFileSerializer(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    per_student_pricing = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    module_count = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'subtitle', 'thumbnail', 'thumbnail_url', 'level', 'language',
            'price', 'sale_price', 'currency', 'is_free', 'status', 'visibility', 'category_name',
            'module_count', 'lesson_count', 'per_student_pricing', 'pricing', 'created_at'
        ]

    def get_module_count(self, obj):
        from modules.models import Module
        from courses.models import CourseModule
        m1 = Module.objects.filter(course=obj, is_active=True).count()
        m2 = CourseModule.objects.filter(course=obj, is_active=True).count()
        return m1 + m2

    def get_lesson_count(self, obj):
        from modules.models import Module
        from lessons.models import Lesson
        from courses.models import CourseModule
        from django.db import models
        m1_ids = list(Module.objects.filter(course=obj, is_active=True).values_list('id', flat=True))
        m2_ids = list(CourseModule.objects.filter(course=obj, is_active=True).values_list('id', flat=True))
        return Lesson.objects.filter(models.Q(module_id__in=m1_ids) | models.Q(module_id__in=m2_ids), is_active=True).count()

    def get_per_student_pricing(self, obj):
        from credits.services import CreditPricingService
        return CreditPricingService.calculate_course_per_student_pricing(obj)

    def get_pricing(self, obj):
        from courses.services import CoursePricingService
        return CoursePricingService.get_course_pricing_dict(obj)

#--------------------------------------------------------------
# Public Curriculum Serializers
#--------------------------------------------------------------

class PublicLessonSerializer(serializers.ModelSerializer):
    video_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    preview_duration_seconds = serializers.SerializerMethodField()
    is_preview = serializers.SerializerMethodField()
    locked = serializers.SerializerMethodField()
    preview_available = serializers.SerializerMethodField()
    public_locked = serializers.SerializerMethodField()
    public_access_state = serializers.SerializerMethodField()

    class Meta:
        from lessons.models import Lesson
        model = Lesson
        fields = [
            'id', 'title', 'lesson_type', 'duration_minutes', 'duration_seconds',
            'preview_duration_seconds', 'is_demo', 'is_preview', 'locked',
            'preview_available', 'public_locked', 'public_access_state',
            'order_index', 'video_url', 'thumbnail_url'
        ]

    def get_is_preview(self, obj):
        return bool(getattr(obj, 'is_demo', False))

    def get_locked(self, obj):
        return not bool(getattr(obj, 'is_demo', False))

    def get_preview_available(self, obj):
        return bool(getattr(obj, 'is_demo', False))

    def get_public_locked(self, obj):
        return not bool(getattr(obj, 'is_demo', False))

    def get_public_access_state(self, obj):
        if not getattr(obj, 'is_demo', False):
            return 'LOCKED'
        primary = obj.media_files.filter(media_role='PRIMARY').first()
        if primary and primary.media_file and getattr(primary.media_file, 'status', 'READY') in ['PROCESSING', 'PENDING']:
            return 'PREVIEW_PROCESSING'
        return 'PREVIEW'

    def get_duration_seconds(self, obj):
        from lessons.services import get_lesson_actual_duration_seconds
        return get_lesson_actual_duration_seconds(obj)

    def get_preview_duration_seconds(self, obj):
        if not getattr(obj, 'is_demo', False):
            return 0
        from lessons.services import get_lesson_actual_duration_seconds, get_public_preview_duration_seconds
        actual_secs = get_lesson_actual_duration_seconds(obj)
        return get_public_preview_duration_seconds(actual_secs)

    def get_thumbnail_url(self, obj):
        if hasattr(obj, 'thumbnail') and obj.thumbnail:
            mf = obj.thumbnail
            storage_key = getattr(mf, 'storage_key', '') or ''
            raw_url = getattr(mf, 'url', '') or getattr(mf, 'file_url', '') or ''
            url_path = raw_url or (f"/media/{storage_key.lstrip('/')}" if storage_key else '')
            request = self.context.get('request') if hasattr(self, 'context') and isinstance(self.context, dict) else None
            return request.build_absolute_uri(url_path) if (request and url_path) else url_path
        return ""

    def get_video_url(self, obj):
        if not getattr(obj, 'is_demo', False):
            return None
        primary = obj.media_files.filter(media_role='PRIMARY').first()
        if primary and primary.media_file:
            mf = primary.media_file
            storage_key = getattr(mf, 'storage_key', '') or ''
            raw_url = getattr(mf, 'file_url', '') or getattr(mf, 'url', '') or ''
            url_path = raw_url or (f"/media/{storage_key.lstrip('/')}" if storage_key else '')
            request = self.context.get('request') if hasattr(self, 'context') and isinstance(self.context, dict) else None
            return request.build_absolute_uri(url_path) if (request and url_path) else url_path
        return getattr(obj, 'external_url', '') or ""

class PublicCourseModuleSerializer(serializers.ModelSerializer):
    lessons = serializers.SerializerMethodField()

    class Meta:
        from modules.models import Module
        model = Module
        fields = ['id', 'title', 'description', 'order_index', 'duration_minutes', 'is_demo', 'lessons']

    def get_lessons(self, obj):
        active_lessons = obj.lessons.filter(is_active=True).order_by('order_index')
        return PublicLessonSerializer(active_lessons, many=True, context=self.context).data

class CourseDetailSerializer(serializers.ModelSerializer):
    thumbnail = MediaFileSerializer(read_only=True)
    promo_video = MediaFileSerializer(read_only=True)
    category = CourseCategorySerializer(read_only=True)
    modules = PublicCourseModuleSerializer(source='course_modules', many=True, read_only=True)
    curriculum = PublicCourseModuleSerializer(source='course_modules', many=True, read_only=True)
    per_student_pricing = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    module_count = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'academy', 'category', 'title', 'slug', 'subtitle', 'short_description', 'description',
            'thumbnail', 'thumbnail_url', 'promo_video', 'promo_video_url', 'level', 'language', 'duration_minutes',
            'price', 'sale_price', 'currency', 'is_free', 'visibility', 'status', 'is_published', 'published_at',
            'demo_enabled', 'demo_duration_days', 'certificate_enabled', 'modules', 'curriculum', 'module_count', 'lesson_count', 'per_student_pricing', 'pricing', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'academy', 'is_published', 'published_at', 'created_at', 'updated_at']

    def get_module_count(self, obj):
        from modules.models import Module
        from courses.models import CourseModule
        m1 = Module.objects.filter(course=obj, is_active=True).count()
        m2 = CourseModule.objects.filter(course=obj, is_active=True).count()
        return m1 + m2

    def get_lesson_count(self, obj):
        from modules.models import Module
        from lessons.models import Lesson
        from courses.models import CourseModule
        from django.db import models
        m1_ids = list(Module.objects.filter(course=obj, is_active=True).values_list('id', flat=True))
        m2_ids = list(CourseModule.objects.filter(course=obj, is_active=True).values_list('id', flat=True))
        return Lesson.objects.filter(models.Q(module_id__in=m1_ids) | models.Q(module_id__in=m2_ids), is_active=True).count()

    def get_per_student_pricing(self, obj):
        from credits.services import CreditPricingService
        return CreditPricingService.calculate_course_per_student_pricing(obj)

    def get_pricing(self, obj):
        from courses.services import CoursePricingService
        return CoursePricingService.get_course_pricing_dict(obj)

class CourseWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = [
            'id', 'slug', 'status', 'category', 'title', 'subtitle', 'short_description', 'description', 'thumbnail',
            'thumbnail_url', 'promo_video', 'promo_video_url', 'level', 'language', 'duration_minutes',
            'price', 'sale_price', 'currency', 'is_free', 'visibility', 'demo_enabled', 'demo_duration_days', 'certificate_enabled'
        ]
        read_only_fields = ['id', 'slug']


