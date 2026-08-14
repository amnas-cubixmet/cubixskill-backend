from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from courses.models import CourseModule, CourseCategory
from courses.selectors import CourseSelector
from courses.services import CourseService
from courses.serializers import (
    CourseListSerializer, CourseDetailSerializer, CourseWriteSerializer,
    CourseCategorySerializer, CourseModuleSerializer
)
from core.permissions import CanAccessAcademyPermission
from core.utils import api_response

#--------------------------------------------------------------
# Course ViewSet
#--------------------------------------------------------------

class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get_serializer_class(self):
        if self.action == 'list':
            return CourseListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return CourseWriteSerializer
        return CourseDetailSerializer

    def get_queryset(self):
        filters = {
            'status': self.request.query_params.get('status'),
            'level': self.request.query_params.get('level'),
            'category': self.request.query_params.get('category'),
            'search': self.request.query_params.get('search')
        }
        return CourseSelector.get_academy_courses(user=self.request.user, filters=filters)

    def perform_create(self, serializer):
        serializer.save(academy=self.request.user.academy)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        course = self.get_object()
        published_course = CourseService.publish_course(course, request.user)
        return api_response(data=CourseDetailSerializer(published_course).data, message="Course published successfully.")

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        course = self.get_object()
        archived_course = CourseService.archive_course(course, request.user)
        return api_response(data=CourseDetailSerializer(archived_course).data, message="Course archived successfully.")

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        course = self.get_object()
        duplicated_course = CourseService.duplicate_course(course, request.user)
        return api_response(
            data=CourseDetailSerializer(duplicated_course).data,
            message="Course duplicated successfully.",
            status_code=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def reorder_modules(self, request, pk=None):
        course = self.get_object()
        module_order_map = request.data.get('module_order_map', {})
        CourseService.reorder_modules(course, module_order_map)
        return api_response(message="Modules reordered successfully.")

#--------------------------------------------------------------
# Category ViewSet
#--------------------------------------------------------------

class CourseCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CourseCategorySerializer

    def get_queryset(self):
        return CourseCategory.objects.filter(academy=self.request.user.academy)

    def perform_create(self, serializer):
        serializer.save(academy=self.request.user.academy)

#--------------------------------------------------------------
# Module ViewSet
#--------------------------------------------------------------

class CourseModuleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CourseModuleSerializer

    def get_queryset(self):
        return CourseModule.objects.filter(course__academy=self.request.user.academy)
