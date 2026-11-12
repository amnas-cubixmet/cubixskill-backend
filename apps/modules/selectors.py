from modules.models import Module
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Module Selectors
#--------------------------------------------------------------

class ModuleSelector:
    LESSON_PREFETCH = (
        'lessons__media_files__media_file',
        'lessons__rich_text',
        'lessons__quiz__questions',
        'lessons__assignment__assets__media_file',
        'lessons__resources__media_file',
    )

    @staticmethod
    def get_course_modules(user, course):
        prefetch = ModuleSelector.LESSON_PREFETCH
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            return Module.objects.filter(course=course).prefetch_related(*prefetch)

        if user.academy and course.academy_id == user.academy.id:
            if user.role_code == SystemRoleCode.STUDENT:
                return Module.objects.filter(course=course, is_active=True).prefetch_related(*prefetch)
            return Module.objects.filter(course=course).prefetch_related(*prefetch)

        return Module.objects.none()
