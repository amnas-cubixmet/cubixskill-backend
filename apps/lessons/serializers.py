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
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'instructions', 'passing_score', 'time_limit_minutes', 'max_attempts', 'shuffle_questions', 'show_result', 'question_count', 'questions']

    def get_question_count(self, obj):
        return obj.questions.count()

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
        fields = ['id', 'title', 'instructions', 'due_date', 'due_days', 'max_marks', 'allow_text_submission', 'allow_file_submission', 'allow_url_submission', 'assets']

from lessons.url_validators import validate_audio_url

#--------------------------------------------------------------
# Primary Lesson Serializer
#--------------------------------------------------------------

class LessonSerializer(serializers.ModelSerializer):
    media_files = LessonMediaSerializer(many=True, read_only=True)
    primary_media = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()
    stream_url = serializers.SerializerMethodField()
    original_url = serializers.SerializerMethodField()
    processing_mode = serializers.SerializerMethodField()
    rich_text = LessonRichTextSerializer(read_only=True)
    quiz = QuizSerializer(read_only=True)
    assignment = AssignmentSerializer(read_only=True)
    resources = LessonResourceSerializer(many=True, read_only=True)
    effective_locked = serializers.SerializerMethodField()
    question_count = serializers.SerializerMethodField()

    media_file_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    media_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    content_source = serializers.CharField(required=False, allow_blank=True, write_only=True)
    content = serializers.JSONField(required=False, allow_null=True, write_only=True)
    resources_payload = serializers.JSONField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Lesson
        fields = [
            'id', 'module', 'title', 'lesson_type', 'description', 'duration_minutes',
            'is_demo', 'is_locked', 'effective_locked', 'allow_download', 'show_media_preview', 'external_url', 'video_url', 'audio_url', 'document_url', 'stream_url', 'original_url', 'processing_mode', 'order_index', 'is_active',
            'media_files', 'primary_media', 'rich_text', 'quiz', 'assignment', 'resources', 'question_count', 'created_at',
            'media_file_id', 'media_id', 'content_source', 'content', 'resources_payload'
        ]
        read_only_fields = ['id', 'module', 'created_at']

    def get_effective_locked(self, obj):
        course = getattr(getattr(obj, 'module', None), 'course', None)
        if not course:
            return False
        from learning_progress.services import StudentCourseProgressionService
        locking_enabled = StudentCourseProgressionService.is_lesson_locking_enabled(course)
        if not locking_enabled:
            return False

        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if not user or not user.is_authenticated:
            return getattr(obj, 'is_locked', False)

        if getattr(user, 'is_staff', False) or (hasattr(course, 'academy') and course.academy and user == getattr(course.academy, 'owner', None)):
            return False

        progression = StudentCourseProgressionService.get_student_course_progression(user, course)
        lesson_info = progression.get('lessons_map', {}).get(str(obj.id))
        if lesson_info:
            return not lesson_info.get('unlocked', True)
        return getattr(obj, 'is_locked', False)

    def get_question_count(self, obj):
        if obj.lesson_type == 'QUIZ' and hasattr(obj, 'quiz') and obj.quiz:
            return obj.quiz.questions.count()
        return 0

    def _get_primary_media_file(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'media_files' in obj._prefetched_objects_cache:
            for mf_link in obj.media_files.all():
                if getattr(mf_link, 'media_role', None) == 'PRIMARY':
                    return getattr(mf_link, 'media_file', None)
            return None
        primary = obj.media_files.filter(media_role='PRIMARY').first()
        return primary.media_file if primary else None

    def get_primary_media(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            return MediaFileSerializer(mf, context=self.context).data
        return None

    def get_video_url(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            if mf.processing_mode == 'hls' and mf.stream_manifest_key:
                url_path = f"/media/{mf.stream_manifest_key.lstrip('/')}"
            else:
                url_path = mf.file_url or f"/media/{mf.storage_key.lstrip('/')}"
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(url_path)
            return url_path
        return obj.external_url or ""

    def get_audio_url(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            url_path = mf.file_url or f"/media/{mf.storage_key.lstrip('/')}"
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(url_path)
            return url_path
        return obj.external_url or ""

    def get_document_url(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            url_path = mf.file_url or f"/media/{mf.storage_key.lstrip('/')}"
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(url_path)
            return url_path
        return obj.external_url or ""

    def get_original_url(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            url_path = mf.file_url or f"/media/{mf.storage_key.lstrip('/')}"
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(url_path)
            return url_path
        return obj.external_url or ""

    def get_stream_url(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf and mf.stream_manifest_key:
            url_path = f"/media/{mf.stream_manifest_key.lstrip('/')}"
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(url_path)
            return url_path
        return ""

    def get_processing_mode(self, obj):
        mf = self._get_primary_media_file(obj)
        if mf:
            return getattr(mf, 'processing_mode', 'direct')
        return "direct"

class LessonCreateSerializer(serializers.ModelSerializer):
    media_file_id = serializers.UUIDField(required=False, allow_null=True)
    media_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    content_source = serializers.CharField(required=False, allow_blank=True, write_only=True)
    content = serializers.JSONField(required=False, allow_null=True, write_only=True)
    rich_text_content = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Lesson
        fields = ['title', 'lesson_type', 'description', 'duration_minutes', 'is_demo', 'is_locked', 'allow_download', 'external_url', 'media_file_id', 'media_id', 'content_source', 'content', 'rich_text_content']

    def validate(self, attrs):
        media_id = attrs.pop('media_id', None)
        if media_id and not attrs.get('media_file_id'):
            attrs['media_file_id'] = media_id

        lesson_type = (attrs.get('lesson_type') or 'VIDEO').upper()
        attrs['lesson_type'] = lesson_type

        content_source = (attrs.get('content_source') or '').lower()
        external_url = (attrs.get('external_url') or '').strip()
        media_file_id = attrs.get('media_file_id')
        is_demo = attrs.get('is_demo', False)

        if lesson_type in ['VIDEO', 'AUDIO', 'DOCUMENT', 'IMAGE']:
            if content_source in ['upload', 'file']:
                if not media_file_id:
                    raise serializers.ValidationError({
                        "media_id": "Uploaded media file ID is required for upload content source."
                    })
                attrs['external_url'] = ''
            elif content_source == 'url':
                if not external_url:
                    raise serializers.ValidationError({
                        "external_url": "External URL is required for URL content source."
                    })
                attrs['media_file_id'] = None
            elif not media_file_id and not external_url:
                raise serializers.ValidationError({
                    "media_id": "Either a media file upload or an external URL is required for media lessons."
                })

        if lesson_type == 'AUDIO' and external_url and content_source != 'upload':
            try:
                attrs['external_url'] = validate_audio_url(external_url)
            except serializers.ValidationError as err:
                raise serializers.ValidationError({"external_url": err.detail})

        if is_demo and external_url and not media_file_id and lesson_type in ['VIDEO', 'AUDIO', 'DOCUMENT', 'IMAGE']:
            raise serializers.ValidationError({
                "external_url": "URL content source is not available for Free Demo / Trial lessons."
            })

        return attrs



