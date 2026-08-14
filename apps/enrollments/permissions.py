from rest_framework import permissions
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# IsStudentOwnerOrAcademyStaff
#--------------------------------------------------------------

class IsStudentOwnerOrAcademyStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if getattr(user, 'is_superuser', False) or getattr(user, 'role_code', '') == SystemRoleCode.SUPER_ADMIN:
            return True

        if obj.student_id == user.id:
            # Student can read own enrollment
            return request.method in permissions.SAFE_METHODS

        if getattr(user, 'academy_id', None) and obj.course.academy_id == user.academy_id:
            # Staff in same academy can perform actions based on role
            return True

        return False
