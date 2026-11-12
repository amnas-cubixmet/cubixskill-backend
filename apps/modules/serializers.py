from lessons.serializers import LessonSerializer
from modules.models import Module
from rest_framework import serializers

#--------------------------------------------------------------
# Module Serializer
#--------------------------------------------------------------

class ModuleSerializer(serializers.ModelSerializer):
    lesson_count = serializers.SerializerMethodField()
    lessons = LessonSerializer(many=True, read_only=True)

    class Meta:
        model = Module
        fields = ['id', 'course', 'title', 'description', 'duration_minutes', 'is_active', 'is_demo', 'order_index', 'lesson_count', 'lessons', 'created_at']
        read_only_fields = ['id', 'course', 'created_at']

    def get_lesson_count(self, obj):
        # Prefer prefetched cache (len) to avoid N+1 from .count() SQL.
        cache = getattr(obj, '_prefetched_objects_cache', None) or {}
        if 'lessons' in cache:
            return len(obj.lessons.all())
        if hasattr(obj, 'annotated_lesson_count'):
            return int(obj.annotated_lesson_count or 0)
        return obj.lessons.count() if hasattr(obj, 'lessons') else 0

class ModuleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['title', 'description', 'is_demo']

class ModuleReorderItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_index = serializers.IntegerField()
