from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from core.utils import CubixSkillAPIException
from enrollments.models import Enrollment, EnrollmentAccessPeriod, EnrollmentEvent, EnrollmentStatus

#--------------------------------------------------------------
# Enrollment Selector
#--------------------------------------------------------------

class EnrollmentSelector:
    @staticmethod
    def get_student_enrollments(user):
        """Returns all enrollments for a specific student user."""
        return Enrollment.objects.filter(student=user).select_related('course', 'course__academy')

    @staticmethod
    def get_academy_enrollments(
        user,
        course_id: str = None,
        status: str = None,
        access_type: str = None,
        source: str = None,
        expired: bool = None,
        expiring_soon: bool = None,
        search: str = None
    ):
        """
        Returns enrollments scoped to the user's Academy (or all if Super Admin).
        """
        qs = Enrollment.objects.select_related('student', 'course', 'course__academy', 'created_by')

        # Tenant isolation
        if not (getattr(user, 'is_superuser', False) or getattr(user, 'role_code', '') == 'SUPER_ADMIN'):
            if getattr(user, 'academy_id', None):
                qs = qs.filter(course__academy_id=user.academy_id)
            else:
                qs = qs.none()

        if course_id:
            qs = qs.filter(course_id=course_id)
        if status:
            qs = qs.filter(status=status)
        if access_type:
            qs = qs.filter(access_type=access_type)
        if source:
            qs = qs.filter(source=source)

        now = timezone.now()
        if expired is True:
            qs = qs.filter(Q(status=EnrollmentStatus.EXPIRED) | Q(is_lifetime=False, access_expires_at__lt=now))
        elif expired is False:
            qs = qs.filter(status=EnrollmentStatus.ACTIVE).filter(Q(is_lifetime=True) | Q(access_expires_at__gte=now))

        if expiring_soon:
            seven_days_later = now + timedelta(days=7)
            qs = qs.filter(status=EnrollmentStatus.ACTIVE, is_lifetime=False, access_expires_at__range=(now, seven_days_later))

        if search:
            qs = qs.filter(
                Q(student__full_name__icontains=search) |
                Q(student__email__icontains=search) |
                Q(course__title__icontains=search)
            )

        return qs.order_by('-enrolled_at')

    @staticmethod
    def get_enrollment_by_id(user, enrollment_id: str) -> Enrollment:
        """
        Fetches single enrollment enforcing permission boundary.
        """
        try:
            enrollment = Enrollment.objects.select_related('student', 'course', 'course__academy').get(id=enrollment_id)
        except Enrollment.DoesNotExist:
            raise CubixSkillAPIException("Enrollment not found.", code="ENROLLMENT_NOT_FOUND", status_code=404)

        # Permission check: Student can view self; Admin can view own academy
        is_super = getattr(user, 'is_superuser', False) or getattr(user, 'role_code', '') == 'SUPER_ADMIN'
        is_owner_student = enrollment.student_id == user.id
        is_same_academy = getattr(user, 'academy_id', None) and user.academy_id == enrollment.course.academy_id

        if not (is_super or is_owner_student or is_same_academy):
            raise CubixSkillAPIException("Permission denied to access this enrollment.", code="PERMISSION_DENIED", status_code=403)

        return enrollment

    @staticmethod
    def get_enrollment_history(enrollment_id: str) -> dict:
        """Retrieves access periods and audit events for an enrollment."""
        periods = EnrollmentAccessPeriod.objects.filter(enrollment_id=enrollment_id).select_related('granted_by')
        events = EnrollmentEvent.objects.filter(enrollment_id=enrollment_id).select_related('performed_by')
        return {
            'periods': list(periods),
            'events': list(events)
        }
