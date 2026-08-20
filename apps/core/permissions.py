from rest_framework import permissions
from users_roles.models import has_permission, can_access_academy

# --------------------------------------------------------------
# Core Platform & Tenant Permission Classes
# --------------------------------------------------------------

class IsAcademyMember(permissions.BasePermission):
    """
    Allows access only to authenticated users belonging to an Academy.
    """
    def has_permission(self, request, view):
        # Never trust an Academy ID supplied by the client.
        return request.user and request.user.is_authenticated and request.user.academy is not None

class HasAcademyPermission(permissions.BasePermission):
    """
    Allows access only to authorized Academy staff matching a specific permission code.
    """
    def __init__(self, permission_code: str):
        self.permission_code = permission_code

    def __call__(self):
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return has_permission(request.user, self.permission_code)

class CanAccessAcademyPermission(permissions.BasePermission):
    """
    Enforces object-level tenant isolation across Academy domains.
    """
    def has_object_permission(self, request, view, obj):
        academy = getattr(obj, 'academy', None)
        if academy is None and hasattr(obj, 'course'):
            academy = getattr(obj.course, 'academy', None)
        if academy is None and hasattr(obj, 'module'):
            academy = getattr(getattr(obj.module, 'course', None), 'academy', None)
        if academy is None and hasattr(obj, 'lesson'):
            module = getattr(obj.lesson, 'module', None)
            course = getattr(module, 'course', None) if module else None
            academy = getattr(course, 'academy', None) if course else None

        if academy is None and isinstance(obj, Academy):
            academy = obj

        return can_access_academy(request.user, academy)
