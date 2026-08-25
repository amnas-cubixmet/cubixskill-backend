from django.db.models import Q, Count
from students.models import StudentProfile
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Student Selectors
#--------------------------------------------------------------

class StudentSelector:
    @staticmethod
    def get_academy_students(user, search_query: str = None, status_filter: str = None, course_id: str = None, ordering: str = None):
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            qs = StudentProfile.objects.all().select_related('user', 'profile_photo')
        else:
            qs = StudentProfile.objects.filter(user__academy=user.academy).select_related('user', 'profile_photo')

        if status_filter and status_filter.upper() != 'ALL':
            qs = qs.filter(status=status_filter.upper())

        if course_id and course_id.lower() != 'all':
            qs = qs.filter(user__enrollments__course_id=course_id)

        if search_query:
            qs = qs.filter(
                Q(display_name__icontains=search_query) |
                Q(student_code__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(user__phone__icontains=search_query) |
                Q(user__full_name__icontains=search_query)
            )

        qs = qs.annotate(enrollments_count=Count('user__enrollments', distinct=True)).distinct()

        SORT_MAP = {
            'recent': '-joined_at',
            'newest': '-joined_at',
            '-joined_at': '-joined_at',
            'oldest': 'joined_at',
            'joined_at': 'joined_at',
            'name_asc': 'display_name',
            'display_name': 'display_name',
            'name_desc': '-display_name',
            '-display_name': '-display_name',
        }
        order_field = SORT_MAP.get(ordering, '-joined_at') if ordering else '-joined_at'
        return qs.order_by(order_field)
