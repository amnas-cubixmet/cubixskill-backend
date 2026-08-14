from functools import wraps
from rest_framework import permissions
from core.utils import CubixSkillAPIException
from features.services import CourseFeatureService, StudentFeatureService
from courses.models import Course

#--------------------------------------------------------------
# HasCourseFeature
#--------------------------------------------------------------

class HasCourseFeature(permissions.BasePermission):
    """
    DRF permission class to verify that a feature code is enabled for the requested course.
    Expects view to specify `feature_code` attribute or `get_feature_code()` method.
    Course ID is extracted from view kwargs (`course_pk`, `course_id`, or `pk`).
    """

    def has_permission(self, request, view):
        feature_code = getattr(view, 'feature_code', None)
        if hasattr(view, 'get_feature_code'):
            feature_code = view.get_feature_code()

        if not feature_code:
            return True  # No feature code constraint specified

        course_id = view.kwargs.get('course_pk') or view.kwargs.get('course_id') or view.kwargs.get('pk')
        if not course_id:
            return True

        try:
            course = Course.objects.get(pk=course_id)
        except (Course.DoesNotExist, ValueError):
            return False

        # If student endpoint, check student feature service
        if getattr(request.user, 'role_code', '') == 'STUDENT':
            return StudentFeatureService.has_course_feature(request.user, course, feature_code)

        # For staff/admin, check course feature enablement
        return CourseFeatureService.has_feature(course, feature_code)


def require_course_feature(feature_code):
    """
    Decorator for API views or methods that require a specific course feature to be enabled.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            course_id = kwargs.get('course_pk') or kwargs.get('course_id') or kwargs.get('pk')
            if not course_id:
                return view_func(request, *args, **kwargs)

            try:
                course = Course.objects.get(pk=course_id)
            except (Course.DoesNotExist, ValueError):
                raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

            # Validate feature access
            if getattr(request.user, 'role_code', '') == 'STUDENT':
                has_access = StudentFeatureService.has_course_feature(request.user, course, feature_code)
            else:
                has_access = CourseFeatureService.has_feature(course, feature_code)

            if not has_access:
                raise CubixSkillAPIException(
                    f"Feature '{feature_code}' is not enabled for this course.",
                    code="FEATURE_NOT_ENABLED",
                    status_code=403
                )

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
