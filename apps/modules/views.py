from core.permissions import CanAccessAcademyPermission
from core.utils import CubixSkillAPIException, api_response
from courses.models import Course
from modules.selectors import ModuleSelector
from modules.serializers import ModuleCreateSerializer, ModuleSerializer
from modules.services import ModuleService
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Course Nested Module ViewSet
#--------------------------------------------------------------

class CourseModuleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = ModuleSerializer

    def get_course(self):
        course_id = self.kwargs.get('course_id')
        user = self.request.user
        try:
            if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
                return Course.objects.get(id=course_id)
            if hasattr(user, 'academy') and user.academy:
                return Course.objects.get(id=course_id, academy=user.academy)
            raise Course.DoesNotExist()
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found or access denied.", code="NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)

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
        return Response(status=status.HTTP_204_NO_CONTENT)

    def reorder(self, request, course_id=None):
        course = self.get_course()
        modules_order = request.data.get('modules', [])
        ModuleService.reorder_course_modules(course, modules_order)
        return api_response(message="Modules reordered successfully.")
