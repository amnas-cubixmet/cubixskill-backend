from lessons.models import Lesson
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Lesson Selectors
#--------------------------------------------------------------

class LessonSelector:
    @staticmethod
    def get_module_lessons(user, module):
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            return Lesson.objects.filter(module=module).prefetch_related('media_files', 'rich_text', 'quiz', 'assignment')
        
        if user.academy and module.course.academy_id == user.academy.id:
            if user.role_code == SystemRoleCode.STUDENT:
                return Lesson.objects.filter(module=module, is_active=True).prefetch_related('media_files', 'rich_text', 'quiz', 'assignment')
            return Lesson.objects.filter(module=module).prefetch_related('media_files', 'rich_text', 'quiz', 'assignment')

        return Lesson.objects.none()
