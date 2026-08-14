from rest_framework import serializers
from lessons.models import Lesson, LessonMedia, LessonRichText, Quiz, Question, QuestionOption, Assignment, AssignmentAsset
from storage.serializers import MediaFileSerializer

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
    rich_text = LessonRichTextSerializer(read_only=True)
    quiz = QuizSerializer(read_only=True)
    assignment = AssignmentSerializer(read_only=True)

    class Meta:
        model = Lesson
        fields = [
            'id', 'module', 'title', 'lesson_type', 'description', 'duration_minutes',
            'is_demo', 'allow_download', 'external_url', 'order_index', 'is_active',
            'media_files', 'rich_text', 'quiz', 'assignment', 'created_at'
        ]
        read_only_fields = ['id', 'module', 'created_at']

class LessonCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['title', 'lesson_type', 'description', 'duration_minutes', 'is_demo', 'allow_download', 'external_url']
