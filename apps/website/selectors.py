from academy.models import Academy
from courses.models import Course, CourseStatus, CourseVisibility
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

# --------------------------------------------------------------
# Website Selectors
# Authoritative read queries for public website pages and course discovery.
# Strictly filters for active, published, publicly visible Courses.
# --------------------------------------------------------------

class WebsiteSelector:

    @classmethod
    def get_public_academy_courses(cls, academy: Academy) -> QuerySet[Course]:
        """
        Retrieves publicly visible, published, active courses for an Academy.
        """
        return Course.objects.filter(
            academy=academy,
            is_active=True,
            status=CourseStatus.PUBLISHED,
            visibility=CourseVisibility.PUBLIC
        ).select_related('category').prefetch_related('modules').order_by('-created_at')

    @classmethod
    def get_public_academy_course_by_slug(cls, academy: Academy, course_identifier: str) -> Course:
        """
        Retrieves a single public course by UUID or slug for an Academy.
        """
        qs = Course.objects.filter(
            academy=academy,
            is_active=True,
            status=CourseStatus.PUBLISHED,
            visibility=CourseVisibility.PUBLIC
        ).select_related('category', 'thumbnail', 'promo_video')

        import uuid
        try:
            val = uuid.UUID(str(course_identifier))
            return get_object_or_404(qs, id=val)
        except (ValueError, TypeError):
            return get_object_or_404(qs, slug=course_identifier)
