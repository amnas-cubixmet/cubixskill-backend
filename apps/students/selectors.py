from django.db.models import Q
from students.models import StudentProfile
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Student Selectors
#--------------------------------------------------------------

class StudentSelector:
    @staticmethod
    def get_academy_students(user, search_query: str = None, status_filter: str = None):
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            qs = StudentProfile.objects.all().select_related('user', 'profile_photo')
        else:
            qs = StudentProfile.objects.filter(user__academy=user.academy).select_related('user', 'profile_photo')

        if status_filter:
            qs = qs.filter(status=status_filter)

        if search_query:
            qs = qs.filter(
                Q(display_name__icontains=search_query) |
                Q(student_code__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        return qs
