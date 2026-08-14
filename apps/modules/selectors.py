from modules.models import Module
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Module Selectors
#--------------------------------------------------------------

class ModuleSelector:
    @staticmethod
    def get_course_modules(user, course):
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            return Module.objects.filter(course=course)
        
        if user.academy and course.academy_id == user.academy.id:
            if user.role_code == SystemRoleCode.STUDENT:
                return Module.objects.filter(course=course, is_active=True)
            return Module.objects.filter(course=course)

        return Module.objects.none()
