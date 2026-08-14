from django.db.models import Q
from courses.models import Course, CourseStatus, CourseVisibility
from users_roles.models import SystemRoleCode

#--------------------------------------------------------------
# Course Selectors
#--------------------------------------------------------------

class CourseSelector:
    @staticmethod
    def get_academy_courses(user, filters: dict = None):
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            qs = Course.objects.all().select_related('academy', 'category', 'thumbnail', 'promo_video')
        elif user.role_code == SystemRoleCode.STUDENT:
            qs = Course.objects.filter(
                academy=user.academy,
                status=CourseStatus.PUBLISHED,
                visibility=CourseVisibility.PUBLIC,
                is_active=True
            ).select_related('academy', 'category', 'thumbnail', 'promo_video')
        else:
            qs = Course.objects.filter(
                academy=user.academy
            ).select_related('academy', 'category', 'thumbnail', 'promo_video')

        if not filters:
            return qs

        if filters.get('status'):
            qs = qs.filter(status=filters['status'])
        if filters.get('level'):
            qs = qs.filter(level=filters['level'])
        if filters.get('category'):
            qs = qs.filter(category_id=filters['category'])
        if filters.get('search'):
            qs = qs.filter(
                Q(title__icontains=filters['search']) |
                Q(short_description__icontains=filters['search'])
            )

        return qs
