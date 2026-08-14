from rest_framework import serializers
from courses.models import Course, CourseCategory, CourseModule
from storage.serializers import MediaFileSerializer

#--------------------------------------------------------------
# Category Serializer
#--------------------------------------------------------------

class CourseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseCategory
        fields = ['id', 'name', 'slug', 'description', 'order_index', 'is_active']
        read_only_fields = ['id', 'slug']

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

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'subtitle', 'thumbnail', 'level', 'language',
            'price', 'currency', 'is_free', 'status', 'visibility', 'category_name', 'created_at'
        ]

class CourseDetailSerializer(serializers.ModelSerializer):
    thumbnail = MediaFileSerializer(read_only=True)
    promo_video = MediaFileSerializer(read_only=True)
    category = CourseCategorySerializer(read_only=True)
    modules = CourseModuleSerializer(many=True, read_only=True)

    class Meta:
        model = Course
        fields = [
            'id', 'academy', 'category', 'title', 'slug', 'subtitle', 'short_description', 'description',
            'thumbnail', 'promo_video', 'level', 'language', 'duration_minutes', 'price', 'currency',
            'is_free', 'visibility', 'status', 'is_published', 'published_at', 'demo_enabled',
            'demo_duration_days', 'certificate_enabled', 'modules', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'academy', 'is_published', 'published_at', 'created_at', 'updated_at']

class CourseWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = [
            'category', 'title', 'subtitle', 'short_description', 'description', 'thumbnail',
            'promo_video', 'level', 'language', 'duration_minutes', 'price', 'currency',
            'is_free', 'visibility', 'demo_enabled', 'demo_duration_days', 'certificate_enabled'
        ]
