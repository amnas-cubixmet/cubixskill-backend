from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from courses.models import Course
from modules.selectors import ModuleSelector
from modules.services import ModuleService
from modules.serializers import ModuleSerializer, ModuleCreateSerializer, ModuleReorderItemSerializer
from core.permissions import CanAccessAcademyPermission
from core.utils import api_response, CubixSkillAPIException

#--------------------------------------------------------------
# Course Nested Module ViewSet
#--------------------------------------------------------------

class CourseModuleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = ModuleSerializer

    def get_course(self):
        course_id = self.kwargs.get('course_id')
        try:
            return Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found.", code="NOT_FOUND", status_code=404)

    def get_queryset(self):
        course = self.get_course()
        return ModuleSelector.get_course_modules(user=self.request.user, course=course)

    def create(self, request, *args, **kwargs):
        course = self.get_course()
        serializer = ModuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        module = ModuleService.create_module(
            course=course,
            title=data['title'],
            description=data.get('description', ''),
            is_demo=data.get('is_demo', False)
        )

        return api_response(
            data=ModuleSerializer(module).data,
            message="Module created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        module = self.get_object()
        ModuleService.delete_module(module)
        return api_response(message="Module deleted successfully.")

    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request, course_id=None):
        course = self.get_course()
        modules_order = request.data.get('modules', [])
        ModuleService.reorder_course_modules(course, modules_order)
        return api_response(message="Modules reordered successfully.")
