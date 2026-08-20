from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from lessons.models import (
    Lesson, LessonMedia, LessonRichText, Quiz, Question, QuestionOption,
    Assignment, AssignmentAsset, LessonResource
)
from modules.models import Module
from lessons.selectors import LessonSelector
from lessons.services import LessonService
from lessons.serializers import (
    LessonSerializer, LessonCreateSerializer, QuizSerializer,
    QuestionSerializer, QuestionOptionSerializer, AssignmentSerializer,
    AssignmentAssetSerializer, LessonResourceSerializer
)
from core.permissions import CanAccessAcademyPermission
from core.utils import api_response, CubixSkillAPIException

#--------------------------------------------------------------
# Module Nested Lesson ViewSet
#--------------------------------------------------------------

class ModuleLessonViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = LessonSerializer

    def get_module(self):
        module_id = self.kwargs.get('module_id')
        try:
            return Module.objects.get(id=module_id)
        except Module.DoesNotExist:
            raise CubixSkillAPIException("Module not found.", code="NOT_FOUND", status_code=404)

    def get_queryset(self):
        module = self.get_module()
        return LessonSelector.get_module_lessons(user=self.request.user, module=module)

    def create(self, request, *args, **kwargs):
        module = self.get_module()
        serializer = LessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lesson = LessonService.create_lesson(
            module=module,
            title=data['title'],
            lesson_type=data['lesson_type'],
            description=data.get('description', ''),
            duration_minutes=data.get('duration_minutes', 0),
            is_demo=data.get('is_demo', False),
            allow_download=data.get('allow_download', False),
            external_url=data.get('external_url', '')
        )

        return api_response(
            data=LessonSerializer(lesson).data,
            message="Lesson created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request, module_id=None):
        module = self.get_module()
        lessons_order = request.data.get('lessons', [])
        LessonService.reorder_lessons(module, lessons_order)
        return api_response(message="Lessons reordered successfully.")

#--------------------------------------------------------------
# Standalone Lesson ViewSet
#--------------------------------------------------------------

class LessonViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = LessonSerializer
    queryset = Lesson.objects.all()

    @action(detail=True, methods=['post'], url_path='media')
    def attach_media(self, request, pk=None):
        lesson = self.get_object()
        media_file_id = request.data.get('media_file_id')
        media_role = request.data.get('media_role', 'PRIMARY')
        caption = request.data.get('caption', '')

        if not media_file_id:
            raise CubixSkillAPIException("media_file_id is required.", code="MEDIA_REQUIRED")

        from storage.models import MediaFile
        try:
            media_file = MediaFile.objects.get(id=media_file_id)
        except MediaFile.DoesNotExist:
            raise CubixSkillAPIException("MediaFile not found.", code="NOT_FOUND", status_code=404)

        lesson_media = LessonService.attach_media(lesson, media_file, media_role=media_role, caption=caption)
        return api_response(
            data={"id": lesson_media.id, "media_file_id": media_file.id, "media_role": media_role, "caption": caption},
            message="Media attached successfully."
        )

    @action(detail=True, methods=['delete'], url_path='media')
    def remove_media(self, request, pk=None):
        lesson = self.get_object()
        media_id = request.data.get('media_id')
        LessonService.detach_media(lesson, media_id=media_id)
        return api_response(message="Media removed successfully.")

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        lesson = self.get_object()
        if lesson.lesson_type in ['VIDEO', 'AUDIO']:
            raise CubixSkillAPIException("Direct download is not permitted for video or audio lessons.", code="DOWNLOAD_FORBIDDEN", status_code=403)
        if not lesson.allow_download:
            raise CubixSkillAPIException("Download is disabled for this lesson.", code="DOWNLOAD_DISABLED", status_code=403)
        primary_media = lesson.media_files.filter(media_role='PRIMARY').first()
        if not primary_media or not primary_media.media_file:
            raise CubixSkillAPIException("No downloadable file found for this lesson.", code="FILE_NOT_FOUND", status_code=404)
        return api_response(
            data={"download_url": primary_media.media_file.file.url, "filename": primary_media.media_file.original_filename},
            message="Download URL retrieved successfully."
        )

    @action(detail=True, methods=['get', 'post'], url_path='resources')
    def resources(self, request, pk=None):
        lesson = self.get_object()
        if request.user and request.user.academy and lesson.module.course.academy != request.user.academy:
            raise CubixSkillAPIException("Permission denied.", code="PERMISSION_DENIED", status_code=403)

        if request.method == 'GET':
            serializer = LessonResourceSerializer(lesson.resources.all(), many=True)
            return api_response(data=serializer.data)

        serializer = LessonResourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = serializer.save(lesson=lesson)
        return api_response(data=LessonResourceSerializer(res).data, message="Resource added successfully.", status_code=status.HTTP_201_CREATED)

#--------------------------------------------------------------
# Lesson Resource ViewSet
#--------------------------------------------------------------

class LessonResourceViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = LessonResourceSerializer
    queryset = LessonResource.objects.all()

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and getattr(user, 'academy', None):
            qs = qs.filter(lesson__module__course__academy=user.academy)
        lesson_id = self.request.query_params.get('lesson_id')
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def create(self, request, *args, **kwargs):
        lesson_id = request.data.get('lesson') or request.data.get('lesson_id')
        if not lesson_id:
            raise CubixSkillAPIException("lesson is required.", code="LESSON_REQUIRED", status_code=400)
        try:
            lesson = Lesson.objects.get(id=lesson_id)
        except (Lesson.DoesNotExist, ValueError):
            raise CubixSkillAPIException("Lesson not found.", code="NOT_FOUND", status_code=404)
        if request.user and getattr(request.user, 'academy', None) and lesson.module.course.academy != request.user.academy:
            raise CubixSkillAPIException("Permission denied.", code="PERMISSION_DENIED", status_code=403)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = serializer.save(lesson=lesson)
        return api_response(
            data=LessonResourceSerializer(res).data,
            message="Lesson resource created successfully.",
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
# Quiz ViewSet
#--------------------------------------------------------------

class QuizViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = QuizSerializer
    queryset = Quiz.objects.all()

#--------------------------------------------------------------
# Question ViewSet
#--------------------------------------------------------------

class QuestionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = QuestionSerializer
    queryset = Question.objects.all()

#--------------------------------------------------------------
# Question Option ViewSet
#--------------------------------------------------------------

class QuestionOptionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = QuestionOptionSerializer
    queryset = QuestionOption.objects.all()

#--------------------------------------------------------------
# Assignment ViewSet
#--------------------------------------------------------------

class AssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssignmentSerializer
    queryset = Assignment.objects.all()

