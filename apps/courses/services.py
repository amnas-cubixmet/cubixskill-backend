from django.db import transaction
from django.utils import timezone
from courses.models import Course, CourseModule, CourseStatus
from core.utils import CubixSkillAPIException

#--------------------------------------------------------------
# Course Business Services
#--------------------------------------------------------------

class CourseService:
    @staticmethod
    def publish_course(course: Course, user) -> Course:
        if not course.title:
            raise CubixSkillAPIException("Course must have a title before publishing.", code="INVALID_COURSE")
        
        course.status = CourseStatus.PUBLISHED
        course.published_at = timezone.now()
        course.save()
        return course

    @staticmethod
    def archive_course(course: Course, user) -> Course:
        course.status = CourseStatus.ARCHIVED
        course.is_active = False
        course.save()
        return course

    @staticmethod
    @transaction.atomic
    def duplicate_course(course: Course, user) -> Course:
        # Create fresh draft copy of course metadata
        new_course = Course.objects.create(
            academy=course.academy,
            category=course.category,
            title=f"{course.title} (Copy)",
            subtitle=course.subtitle,
            short_description=course.short_description,
            description=course.description,
            thumbnail=course.thumbnail,
            promo_video=course.promo_video,
            level=course.level,
            language=course.language,
            duration_minutes=course.duration_minutes,
            price=course.price,
            currency=course.currency,
            is_free=course.is_free,
            visibility=course.visibility,
            status=CourseStatus.DRAFT,
            demo_enabled=course.demo_enabled,
            demo_duration_days=course.demo_duration_days,
            certificate_enabled=course.certificate_enabled
        )

        # Duplicate Modules
        for module in course.modules.all():
            CourseModule.objects.create(
                course=new_course,
                title=module.title,
                description=module.description,
                order_index=module.order_index,
                is_active=module.is_active
            )

        return new_course

    @staticmethod
    @transaction.atomic
    def reorder_modules(course: Course, module_order_map: dict) -> None:
        """
        module_order_map format: { "module_uuid": new_index_int }
        """
        for module in course.modules.all():
            str_id = str(module.id)
            if str_id in module_order_map:
                module.order_index = int(module_order_map[str_id])
                module.save(update_fields=['order_index'])
