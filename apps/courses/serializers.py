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

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'subtitle', 'thumbnail', 'thumbnail_url', 'level', 'language',
            'price', 'sale_price', 'currency', 'is_free', 'status', 'visibility', 'category_name', 'per_student_pricing', 'pricing', 'created_at'
        ]

    def get_per_student_pricing(self, obj):
        from credits.services import CreditPricingService
        return CreditPricingService.calculate_course_per_student_pricing(obj)

    def get_pricing(self, obj):
        from courses.services import CoursePricingService
        return CoursePricingService.get_course_pricing_dict(obj)

class CourseDetailSerializer(serializers.ModelSerializer):
    thumbnail = MediaFileSerializer(read_only=True)
    promo_video = MediaFileSerializer(read_only=True)
    category = CourseCategorySerializer(read_only=True)
    modules = CourseModuleSerializer(many=True, read_only=True)
    per_student_pricing = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'academy', 'category', 'title', 'slug', 'subtitle', 'short_description', 'description',
            'thumbnail', 'thumbnail_url', 'promo_video', 'promo_video_url', 'level', 'language', 'duration_minutes',
            'price', 'sale_price', 'currency', 'is_free', 'visibility', 'status', 'is_published', 'published_at',
            'demo_enabled', 'demo_duration_days', 'certificate_enabled', 'modules', 'per_student_pricing', 'pricing', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'academy', 'is_published', 'published_at', 'created_at', 'updated_at']

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


