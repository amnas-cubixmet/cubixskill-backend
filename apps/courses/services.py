from core.utils import CubixSkillAPIException
from courses.models import Course, CourseModule, CourseStatus
from django.db import transaction
from django.utils import timezone

#--------------------------------------------------------------
# Course Publish Readiness Service
#--------------------------------------------------------------

class CoursePublishReadinessService:
    """
    Authoritative backend service to calculate Course Draft / Publish Readiness.
    Evaluates real persisted DB records for Modules, Lessons, Media, and Metadata.
    """
    @staticmethod
    def get_readiness(course: Course) -> dict:
        from lessons.models import Lesson, LessonMedia
        from modules.models import Module
        from storage.models import ProcessingStatus

        # 1. Real Canonical Module Count from DB
        module_qs = Module.objects.filter(course=course, is_active=True)
        module_count = module_qs.count()

        # 2. Real Canonical Lesson Count from DB
        lesson_qs = Lesson.objects.filter(module__course=course, is_active=True)
        lesson_count = lesson_qs.count()

        # 3. Video Processing / HLS Status
        processing_count = 0
        try:
            processing_count = LessonMedia.objects.filter(
                lesson__in=lesson_qs,
                media_file__processing_status__in=[
                    ProcessingStatus.QUEUED,
                    ProcessingStatus.PROCESSING,
                    ProcessingStatus.UPLOADED
                ]
            ).count()
        except Exception:
            processing_count = 0

        # Readiness Checklist Items
        title = (course.title or "").strip()
        has_title = bool(title)
        has_category = bool(course.category_id)
        
        thumbnail_url = getattr(course, 'thumbnail_url', '') or ''
        has_thumbnail = bool(course.thumbnail_id or (thumbnail_url and thumbnail_url.strip()))

        has_modules = module_count >= 1
        has_lessons = lesson_count >= 1
        video_processing_complete = processing_count == 0

        category_name = "Added"
        if has_category and hasattr(course, 'category') and course.category:
            category_name = getattr(course.category, 'name', 'Added')

        checklist_items = [
            {
                "key": "title",
                "label": "Course Title",
                "required": True,
                "complete": has_title,
                "value_text": title if has_title else "Missing"
            },
            {
                "key": "category",
                "label": "Course Category",
                "required": True,
                "complete": has_category,
                "value_text": category_name if has_category else "Missing"
            },
            {
                "key": "thumbnail",
                "label": "Thumbnail / Course Image",
                "required": True,
                "complete": has_thumbnail,
                "value_text": "Added" if has_thumbnail else "Missing"
            },
            {
                "key": "modules",
                "label": "Curriculum Modules",
                "required": True,
                "complete": has_modules,
                "count": module_count,
                "value_text": f"{module_count} Module{'s' if module_count != 1 else ''}"
            },
            {
                "key": "lessons",
                "label": "Curriculum Lessons",
                "required": True,
                "complete": has_lessons,
                "count": lesson_count,
                "value_text": f"{lesson_count} Lesson{'s' if lesson_count != 1 else ''}"
            },
            {
                "key": "video_processing",
                "label": "Video HLS Processing",
                "required": False,
                "complete": video_processing_complete,
                "count": processing_count,
                "status": "PROCESSING" if not video_processing_complete else "READY",
                "value_text": f"{processing_count} Video{'s' if processing_count != 1 else ''} Processing" if not video_processing_complete else "All Media Ready"
            }
        ]

        ready_to_publish = all(
            item["complete"]
            for item in checklist_items
            if item["required"]
        )

        missing_required = [item for item in checklist_items if item["required"] and not item["complete"]]

        return {
            "course_id": str(course.id),
            "status": course.status,
            "ready_to_publish": ready_to_publish,
            "module_count": module_count,
            "lesson_count": lesson_count,
            "processing_count": processing_count,
            "remaining_required_count": len(missing_required),
            "items": checklist_items
        }

#--------------------------------------------------------------
# Course Business Services
#--------------------------------------------------------------

class CourseService:
    @staticmethod
    def publish_course(course: Course, user) -> Course:
        readiness = CoursePublishReadinessService.get_readiness(course)
        if not readiness["ready_to_publish"]:
            missing = [item["label"] for item in readiness["items"] if item["required"] and not item["complete"]]
            raise CubixSkillAPIException(
                f"Cannot publish course. Please complete required items: {', '.join(missing)}",
                code="PUBLISH_NOT_READY"
            )

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


#--------------------------------------------------------------
# Centralized Course Pricing Service
#--------------------------------------------------------------

from decimal import Decimal


class CoursePricingService:
    """
    Centralized source of truth for course pricing, sale discounts, and effective price rules.
    """

    @staticmethod
    def get_course_effective_price(course) -> Decimal:
        if not course or course.is_free:
            return Decimal("0.00")

        price = Decimal(str(course.price)) if course.price is not None else Decimal("0.00")

        if (
            course.sale_price is not None
            and Decimal(str(course.sale_price)) >= Decimal("0.00")
            and Decimal(str(course.sale_price)) < price
        ):
            return Decimal(str(course.sale_price))

        return price

    @staticmethod
    def get_course_pricing_dict(course) -> dict:
        if not course:
            return {
                "regular_price": "0.00",
                "sale_price": None,
                "effective_price": "0.00",
                "sale_discount": "0.00",
                "is_on_sale": False,
                "is_free": True,
                "currency": "INR",
            }

        regular_price = Decimal(str(course.price)).quantize(Decimal('0.01')) if course.price is not None else Decimal('0.00')
        raw_sale_price = Decimal(str(course.sale_price)).quantize(Decimal('0.01')) if course.sale_price is not None else None

        is_on_sale = (
            not course.is_free
            and raw_sale_price is not None
            and raw_sale_price >= Decimal("0.00")
            and raw_sale_price < regular_price
        )

        effective_price = CoursePricingService.get_course_effective_price(course).quantize(Decimal('0.01'))
        sale_discount = max(Decimal('0.00'), regular_price - effective_price)

        return {
            "regular_price": str(regular_price),
            "sale_price": str(raw_sale_price) if is_on_sale else None,
            "effective_price": str(effective_price),
            "sale_discount": str(sale_discount),
            "is_on_sale": is_on_sale,
            "is_free": course.is_free or effective_price == Decimal('0.00'),
            "currency": getattr(course, 'currency', 'INR') or 'INR',
        }

