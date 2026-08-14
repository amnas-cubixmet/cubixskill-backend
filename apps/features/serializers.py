from rest_framework import serializers
from features.models import Feature, CourseFeature, FeatureScope

#--------------------------------------------------------------
# FeatureSerializer
#--------------------------------------------------------------

class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            'id',
            'name',
            'code',
            'description',
            'category',
            'scope',
            'frontend_key',
            'frontend_route',
            'icon_key',
            'sort_order',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        value = value.strip().lower()
        if self.instance and self.instance.code != value:
            raise serializers.ValidationError("Feature code is immutable once created.")
        return value

#--------------------------------------------------------------
# CourseFeatureSerializer
#--------------------------------------------------------------
class CourseFeatureSerializer(serializers.ModelSerializer):
    feature_code = serializers.CharField(source='feature.code', read_only=True)
    feature_name = serializers.CharField(source='feature.name', read_only=True)
    feature_category = serializers.CharField(source='feature.category', read_only=True)

    class Meta:
        model = CourseFeature
        fields = [
            'id',
            'course',
            'feature',
            'feature_code',
            'feature_name',
            'feature_category',
            'is_enabled',
            'config',
            'enabled_by',
            'enabled_at',
            'disabled_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'enabled_by', 'enabled_at', 'disabled_at', 'created_at', 'updated_at']

#--------------------------------------------------------------
# CourseFeatureToggleSerializer
#--------------------------------------------------------------

class CourseFeatureToggleSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=True)
    config = serializers.JSONField(required=False, default=dict)

#--------------------------------------------------------------
# AcademyFeatureSummarySerializer
#--------------------------------------------------------------

class AcademyFeatureSummarySerializer(serializers.Serializer):
    feature_id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    enabled_course_count = serializers.IntegerField()
