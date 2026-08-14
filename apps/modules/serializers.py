from rest_framework import serializers
from modules.models import Module

#--------------------------------------------------------------
# Module Serializer
#--------------------------------------------------------------

class ModuleSerializer(serializers.ModelSerializer):
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = ['id', 'course', 'title', 'description', 'duration_minutes', 'is_active', 'is_demo', 'order_index', 'lesson_count', 'created_at']
        read_only_fields = ['id', 'course', 'created_at']

    def get_lesson_count(self, obj):
        if hasattr(obj, 'lessons'):
            return obj.lessons.count()
        return 0

class ModuleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['title', 'description', 'is_demo']

class ModuleReorderItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_index = serializers.IntegerField()
