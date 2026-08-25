from rest_framework import serializers
from lessons.models import (
    Lesson, LessonMedia, LessonRichText, Quiz, Question, QuestionOption,
    Assignment, AssignmentAsset, LessonResource
)
from storage.models import MediaFile
from storage.serializers import MediaFileSerializer

#--------------------------------------------------------------
# Lesson Resource Serializer
#--------------------------------------------------------------

class LessonResourceSerializer(serializers.ModelSerializer):
    media_file = MediaFileSerializer(read_only=True)
    media_file_id = serializers.PrimaryKeyRelatedField(
        queryset=MediaFile.objects.all(), source='media_file', write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = LessonResource
        fields = ['id', 'lesson', 'media_file', 'media_file_id', 'title', 'url', 'description', 'resource_type', 'allow_download', 'order_index', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'lesson': {'required': False, 'allow_null': True},
            'url': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        media_file = attrs.get('media_file')
        url = attrs.get('url')
        
        # If updating, pull existing values for omitted fields
        if self.instance:
            if media_file is None and 'media_file' not in attrs:
                media_file = self.instance.media_file
            if url is None and 'url' not in attrs:
                url = self.instance.url

        if not media_file and not (url and url.strip()):
            raise serializers.ValidationError("Either a valid file upload (media_file_id) or an external URL is required.")

        return attrs

#--------------------------------------------------------------
# Lesson Media Serializer
#--------------------------------------------------------------

class LessonMediaSerializer(serializers.ModelSerializer):
    media_file = MediaFileSerializer(read_only=True)

    class Meta:
        model = LessonMedia
        fields = ['id', 'media_file', 'media_role', 'caption', 'created_at']

#--------------------------------------------------------------
# Lesson Rich Text Serializer
#--------------------------------------------------------------

class LessonRichTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonRichText
        fields = ['id', 'content']

#--------------------------------------------------------------
# Question Option Serializer
#--------------------------------------------------------------

class QuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ['id', 'option_text', 'is_correct', 'order_index']

#--------------------------------------------------------------
# Question Serializer
#--------------------------------------------------------------

class QuestionSerializer(serializers.ModelSerializer):
    options = QuestionOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'question_type', 'question_text', 'explanation', 'points', 'required', 'answer_text', 'order_index', 'options']

#--------------------------------------------------------------
# Quiz Serializer
#--------------------------------------------------------------

class QuizSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'instructions', 'passing_score', 'time_limit_minutes', 'max_attempts', 'shuffle_questions', 'show_result', 'questions']

#--------------------------------------------------------------
# Assignment Asset Serializer
#--------------------------------------------------------------

class AssignmentAssetSerializer(serializers.ModelSerializer):
    media_file = MediaFileSerializer(read_only=True)

    class Meta:
        model = AssignmentAsset
        fields = ['id', 'media_file', 'asset_type', 'title', 'description', 'order_index']

#--------------------------------------------------------------
# Assignment Serializer
#--------------------------------------------------------------

class AssignmentSerializer(serializers.ModelSerializer):
    assets = AssignmentAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Assignment
        fields = ['id', 'title', 'instructions', 'due_date', 'max_marks', 'allow_text_submission', 'allow_file_submission', 'allow_url_submission', 'assets']

#--------------------------------------------------------------
# Primary Lesson Serializer
#--------------------------------------------------------------

class LessonSerializer(serializers.ModelSerializer):
    media_files = LessonMediaSerializer(many=True, read_only=True)
    primary_media = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    rich_text = LessonRichTextSerializer(read_only=True)
    quiz = QuizSerializer(read_only=True)
    assignment = AssignmentSerializer(read_only=True)
    resources = LessonResourceSerializer(many=True, read_only=True)

    class Meta:
        model = Lesson
        fields = [
            'id', 'module', 'title', 'lesson_type', 'description', 'duration_minutes',
            'is_demo', 'allow_download', 'external_url', 'video_url', 'order_index', 'is_active',
            'media_files', 'primary_media', 'rich_text', 'quiz', 'assignment', 'resources', 'created_at'
        ]
        read_only_fields = ['id', 'module', 'created_at']

    def get_primary_media(self, obj):
        primary = obj.media_files.filter(media_role='PRIMARY').first()
        if primary and primary.media_file:
            return MediaFileSerializer(primary.media_file).data
        return None

    def get_video_url(self, obj):
        primary = obj.media_files.filter(media_role='PRIMARY').first()
        if primary and primary.media_file:
            return primary.media_file.file_url or f"/media/{primary.media_file.storage_key.lstrip('/')}"
        return obj.external_url or ""

class LessonCreateSerializer(serializers.ModelSerializer):
    media_file_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Lesson
        fields = ['title', 'lesson_type', 'description', 'duration_minutes', 'is_demo', 'allow_download', 'external_url', 'media_file_id']

