from core.permissions import CanAccessAcademyPermission
from core.utils import CubixSkillAPIException, api_response
from django.db import transaction
from lessons.models import (
    Assignment,
    Lesson,
    LessonMedia,
    LessonResource,
    Question,
    QuestionOption,
    Quiz,
)
from lessons.selectors import LessonSelector
from lessons.serializers import (
    AssignmentSerializer,
    LessonCreateSerializer,
    LessonResourceSerializer,
    LessonSerializer,
    QuestionOptionSerializer,
    QuestionSerializer,
    QuizSerializer,
)
from lessons.services import LessonService
from modules.models import Module
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

#--------------------------------------------------------------
# Module Nested Lesson ViewSet
#--------------------------------------------------------------

class ModuleLessonViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = LessonSerializer

    def get_module(self):
        module_id = self.kwargs.get('module_id')
        import uuid
        try:
            valid_uuid = uuid.UUID(str(module_id))
        except (ValueError, TypeError):
            raise CubixSkillAPIException("Invalid module ID format.", code="INVALID_UUID", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            module = Module.objects.select_related('course', 'course__academy').get(id=valid_uuid)
        except Module.DoesNotExist:
            raise CubixSkillAPIException("Module not found.", code="NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)

        user = self.request.user
        if user and getattr(user, 'academy', None) and module.course and module.course.academy != user.academy:
            if not getattr(user, 'is_superuser', False) and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                raise CubixSkillAPIException("Permission denied: Module belongs to another Academy.", code="PERMISSION_DENIED", status_code=status.HTTP_403_FORBIDDEN)

        return module

    def get_queryset(self):
        module = self.get_module()
        return LessonSelector.get_module_lessons(user=self.request.user, module=module)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if data.get('effective_locked'):
            raise CubixSkillAPIException("This lesson is locked. Complete required previous lessons to access.", code="LESSON_LOCKED", status_code=status.HTTP_403_FORBIDDEN)
        return Response(data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        module = self.get_module()
        serializer = LessonCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(
                data={"fields": serializer.errors},
                message="Lesson validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="VALIDATION_ERROR"
            )

        data = serializer.validated_data

        media_file_id = data.pop('media_file_id', None) or request.data.get('media_file_id') or request.data.get('media_id')
        raw_content = data.pop('content', None) or request.data.get('content')
        rich_content = data.pop('rich_text_content', None) or request.data.get('text_content') or (raw_content if isinstance(raw_content, str) else '')

        lesson = LessonService.create_lesson(
            module=module,
            title=data['title'],
            lesson_type=data['lesson_type'],
            description=data.get('description', ''),
            duration_minutes=data.get('duration_minutes', 0),
            is_demo=data.get('is_demo', False),
            is_locked=data.get('is_locked', False),
            allow_download=data.get('allow_download', False),
            external_url=data.get('external_url', '')
        )

        if data['lesson_type'] == 'QUIZ':
            quiz_payload = raw_content if isinstance(raw_content, dict) else request.data
            LessonService.save_quiz_data(lesson, quiz_payload)

        if data['lesson_type'] in ['ASSIGNMENT', 'PROJECT']:
            assignment_payload = raw_content if isinstance(raw_content, dict) else request.data
            LessonService.save_assignment_data(lesson, assignment_payload)

        if rich_content and data['lesson_type'] == 'RICH_TEXT':
            LessonService.set_rich_text(lesson, rich_content)

        if media_file_id:
            from storage.models import MediaFile
            try:
                media_file = MediaFile.objects.get(id=media_file_id)
                # Cross-Academy Security check
                if module.course and module.course.academy and media_file.academy_uuid != module.course.academy.id:
                    raise CubixSkillAPIException("Permission denied: Cannot attach media from another Academy.", code="CROSS_ACADEMY_MEDIA_FORBIDDEN", status_code=403)
                LessonService.attach_media(lesson, media_file, media_role='PRIMARY')
            except MediaFile.DoesNotExist:
                raise CubixSkillAPIException("MediaFile not found.", code="NOT_FOUND", status_code=404)

        resources_data = request.data.get('resources')
        if not resources_data and isinstance(raw_content, dict):
            resources_data = raw_content.get('resources')
        if resources_data and isinstance(resources_data, list):
            LessonService.save_resources_data(lesson, resources_data)

        return api_response(
            data=LessonSerializer(lesson, context={'request': request}).data,
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

    def get_queryset(self):
        qs = Lesson.objects.select_related('module', 'module__course', 'module__course__academy')
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            acad_id = getattr(user, 'academy_id', None) or getattr(getattr(user, 'academy', None), 'id', None)
            if acad_id:
                qs = qs.filter(module__course__academy_id=acad_id)
        return qs

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        lesson = serializer.save()

        content_source = (request.data.get('content_source') or '').lower()
        media_file_id = request.data.get('media_file_id') or request.data.get('media_id')

        if content_source in ['upload', 'file']:
            if media_file_id:
                from storage.models import MediaFile
                try:
                    media_file = MediaFile.objects.get(id=media_file_id)
                    if lesson.module and lesson.module.course and media_file.academy_uuid != lesson.module.course.academy.id:
                        raise CubixSkillAPIException("Permission denied: Cannot attach media from another Academy.", code="CROSS_ACADEMY_MEDIA_FORBIDDEN", status_code=403)
                    LessonMedia.objects.update_or_create(
                        lesson=lesson,
                        media_role='PRIMARY',
                        defaults={'media_file': media_file}
                    )
                except MediaFile.DoesNotExist:
                    raise CubixSkillAPIException("MediaFile not found.", code="NOT_FOUND", status_code=404)
            if 'external_url' in request.data:
                lesson.external_url = ''
                lesson.save(update_fields=['external_url'])
        elif content_source == 'url':
            LessonMedia.objects.filter(lesson=lesson, media_role='PRIMARY').delete()
            ext_url = (request.data.get('external_url') or '').strip()
            lesson.external_url = ext_url
            lesson.save(update_fields=['external_url'])
        elif media_file_id:
            from storage.models import MediaFile
            try:
                media_file = MediaFile.objects.get(id=media_file_id)
                if lesson.module and lesson.module.course and media_file.academy_uuid != lesson.module.course.academy.id:
                    raise CubixSkillAPIException("Permission denied: Cannot attach media from another Academy.", code="CROSS_ACADEMY_MEDIA_FORBIDDEN", status_code=403)
                LessonMedia.objects.update_or_create(
                    lesson=lesson,
                    media_role='PRIMARY',
                    defaults={'media_file': media_file}
                )
            except MediaFile.DoesNotExist:
                raise CubixSkillAPIException("MediaFile not found.", code="NOT_FOUND", status_code=404)

        if lesson.lesson_type == 'QUIZ':
            quiz_payload = request.data.get('content') if isinstance(request.data.get('content'), dict) else request.data
            if quiz_payload:
                LessonService.save_quiz_data(lesson, quiz_payload)

        if lesson.lesson_type in ['ASSIGNMENT', 'PROJECT']:
            assignment_payload = request.data.get('content') if isinstance(request.data.get('content'), dict) else request.data
            if assignment_payload:
                LessonService.save_assignment_data(lesson, assignment_payload)

        rich_content = request.data.get('content') or request.data.get('text_content') or request.data.get('rich_text_content')
        if rich_content and lesson.lesson_type == 'RICH_TEXT':
            LessonService.set_rich_text(lesson, rich_content)

        resources_data = request.data.get('resources') or request.data.get('resources_payload')
        if not resources_data and isinstance(request.data.get('content'), dict):
            resources_data = request.data.get('content', {}).get('resources')
        if resources_data and isinstance(resources_data, list):
            LessonService.save_resources_data(lesson, resources_data)

        return api_response(
            data=LessonSerializer(lesson, context={'request': request}).data,
            message="Lesson updated successfully."
        )

    @action(detail=True, methods=['post'], url_path='media')
    def attach_media(self, request, pk=None):
        lesson = self.get_object()
        media_file_id = request.data.get('media_file_id') or request.data.get('media_id')
        media_role = request.data.get('media_role', 'PRIMARY')
        caption = request.data.get('caption', '')

        if not media_file_id:
            raise CubixSkillAPIException("media_file_id is required.", code="MEDIA_REQUIRED")

        from storage.models import MediaFile
        try:
            media_file = MediaFile.objects.get(id=media_file_id)
        except MediaFile.DoesNotExist:
            raise CubixSkillAPIException("MediaFile not found.", code="NOT_FOUND", status_code=404)

        if lesson.module and lesson.module.course and media_file.academy_uuid != lesson.module.course.academy.id:
            raise CubixSkillAPIException("Permission denied: Cannot attach media from another Academy.", code="CROSS_ACADEMY_MEDIA_FORBIDDEN", status_code=403)

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
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = QuizSerializer
    queryset = Quiz.objects.all()

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and getattr(user, 'academy', None):
            if not getattr(user, 'is_superuser', False) and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                qs = qs.filter(lesson__module__course__academy=user.academy)
        return qs

    def update(self, request, *args, **kwargs):
        quiz = self.get_object()
        user = request.user
        if user and getattr(user, 'academy', None) and quiz.lesson and quiz.lesson.module and quiz.lesson.module.course:
            if quiz.lesson.module.course.academy != user.academy:
                if not getattr(user, 'is_superuser', False) and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                    raise CubixSkillAPIException("Permission denied.", code="PERMISSION_DENIED", status_code=status.HTTP_403_FORBIDDEN)
        
        LessonService.save_quiz_data(quiz.lesson, request.data)
        quiz.refresh_from_db()
        return api_response(
            data=QuizSerializer(quiz, context={'request': request}).data,
            message="Quiz updated successfully."
        )

class QuestionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = QuestionSerializer
    queryset = Question.objects.all()

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and getattr(user, 'academy', None):
            if not getattr(user, 'is_superuser', False) and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                qs = qs.filter(quiz__lesson__module__course__academy=user.academy)
        return qs

class QuestionOptionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = QuestionOptionSerializer
    queryset = QuestionOption.objects.all()

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and getattr(user, 'academy', None):
            if not getattr(user, 'is_superuser', False) and getattr(user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                qs = qs.filter(question__quiz__lesson__module__course__academy=user.academy)
        return qs

#--------------------------------------------------------------
# Assignment ViewSet
#--------------------------------------------------------------

class AssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssignmentSerializer
    queryset = Assignment.objects.all()

