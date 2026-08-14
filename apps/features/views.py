from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from core.utils import CubixSkillAPIException
from courses.models import Course
from academy.models import Academy
from features.models import Feature, CourseFeature
from features.serializers import (
    FeatureSerializer,
    CourseFeatureSerializer,
    CourseFeatureToggleSerializer,
    AcademyFeatureSummarySerializer,
)
from features.services import (
    CourseFeatureService,
    StudentFeatureService,
    AcademyFeatureService,
)

class IsSuperAdminOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, 'is_superuser', False):
            return True
        role = getattr(request.user, 'role_code', '')
        return role in ['SUPER_ADMIN', 'ACADEMY_ADMIN', 'INSTRUCTOR']


class FeatureViewSet(viewsets.ModelViewSet):
    """
    Super Admin / Staff registry endpoints for globally managing features.
    """
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [IsSuperAdminOrStaff]
    lookup_field = 'code'

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset


class CourseFeatureViewSet(viewsets.ViewSet):
    """
    Endpoints for managing and checking Course Features.
    GET /api/v1/courses/{course_id}/features/
    POST /api/v1/courses/{course_id}/features/{feature_code}/enable/
    POST /api/v1/courses/{course_id}/features/{feature_code}/disable/
    """
    permission_classes = [IsSuperAdminOrStaff]

    def list(self, request, course_id=None):
        course = get_object_or_404(Course, pk=course_id)
        # Verify tenant boundary if academy_admin/instructor
        user_academy = getattr(request.user, 'academy_id', None)
        if user_academy and course.academy_id and user_academy != course.academy_id:
            raise CubixSkillAPIException("Access denied to course in another academy.", code="CROSS_ACADEMY_FORBIDDEN", status_code=403)

        features = CourseFeatureService.get_features(course)
        return Response({"course_id": str(course.id), "features": features})

    @action(detail=False, methods=['post'], url_path='(?P<feature_code>[^/.]+)/enable')
    def enable_feature(self, request, course_id=None, feature_code=None):
        course = get_object_or_404(Course, pk=course_id)
        user_academy = getattr(request.user, 'academy_id', None)
        if user_academy and course.academy_id and user_academy != course.academy_id:
            raise CubixSkillAPIException("Access denied to course in another academy.", code="CROSS_ACADEMY_FORBIDDEN", status_code=403)

        config = request.data.get('config', None)
        cf = CourseFeatureService.enable_feature(course, feature_code, user=request.user, config=config)
        return Response({
            "message": f"Feature '{feature_code}' enabled for course.",
            "feature_code": feature_code,
            "is_enabled": cf.is_enabled,
            "config": cf.config
        })

    @action(detail=False, methods=['post'], url_path='(?P<feature_code>[^/.]+)/disable')
    def disable_feature(self, request, course_id=None, feature_code=None):
        course = get_object_or_404(Course, pk=course_id)
        user_academy = getattr(request.user, 'academy_id', None)
        if user_academy and course.academy_id and user_academy != course.academy_id:
            raise CubixSkillAPIException("Access denied to course in another academy.", code="CROSS_ACADEMY_FORBIDDEN", status_code=403)

        cf = CourseFeatureService.disable_feature(course, feature_code, user=request.user)
        return Response({
            "message": f"Feature '{feature_code}' disabled for course.",
            "feature_code": feature_code,
            "is_enabled": cf.is_enabled
        })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def student_course_features_view(request, course_id):
    """
    GET /api/v1/student/courses/{course_id}/features/
    Returns feature entitlement boolean dictionary for an enrolled student.
    """
    course = get_object_or_404(Course, pk=course_id)
    features_dict = StudentFeatureService.get_course_features(request.user, course)
    return Response({"course_id": str(course.id), "features": features_dict})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def student_available_features_view(request):
    """
    GET /api/v1/student/features/
    Returns list of distinct feature codes available across all student's active enrollments.
    """
    available_codes = StudentFeatureService.get_available_features(request.user)
    return Response({"features": available_codes})


@api_view(['GET'])
@permission_classes([IsSuperAdminOrStaff])
def academy_features_summary_view(request):
    """
    GET /api/v1/academy/features/
    Derives feature summary from the active academy's courses.
    """
    academy_id = request.query_params.get('academy_id') or getattr(request.user, 'academy_id', None)
    if not academy_id:
        raise CubixSkillAPIException("Academy ID required.", code="ACADEMY_REQUIRED", status_code=400)

    academy = get_object_or_404(Academy, pk=academy_id)
    summary = AcademyFeatureService.get_academy_used_features(academy)
    return Response({"academy_id": str(academy.id), "features": summary})
