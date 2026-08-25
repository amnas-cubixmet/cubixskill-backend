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

