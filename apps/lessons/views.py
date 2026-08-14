from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from lessons.models import Lesson, Quiz, Question, QuestionOption, Assignment, AssignmentAsset
from modules.models import Module
from lessons.selectors import LessonSelector
from lessons.services import LessonService
from lessons.serializers import (
    LessonSerializer, LessonCreateSerializer, QuizSerializer,
    QuestionSerializer, QuestionOptionSerializer, AssignmentSerializer, AssignmentAssetSerializer
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
