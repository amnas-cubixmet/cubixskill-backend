from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from django.core.cache import cache
from core.utils import CubixSkillAPIException
from enrollments.services import EnrollmentAccessService
from features.models import Feature, CourseFeature

class CourseFeatureService:
    """
    Centralized service for managing and resolving Course-level feature activation.
    Features must be globally active (Feature.is_active=True) AND course-enabled (CourseFeature.is_enabled=True).
    """

    @staticmethod
    def get_cache_key(course_id, feature_code=None):
        if feature_code:
            return f"course:{course_id}:feature:{feature_code}"
        return f"course:{course_id}:features"

    @staticmethod
    def invalidate_course_cache(course_id, feature_code=None):
        cache.delete(CourseFeatureService.get_cache_key(course_id))
        if feature_code:
            cache.delete(CourseFeatureService.get_cache_key(course_id, feature_code))

    @staticmethod
    def has_feature(course, feature_code: str) -> bool:
        """
        Returns True if the feature is globally active AND enabled for the given course.
        """
        if not course or not feature_code:
            return False

        cache_key = CourseFeatureService.get_cache_key(course.id, feature_code)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Check existence and status
        result = CourseFeature.objects.filter(
            course=course,
            feature__code=feature_code,
            feature__is_active=True,
            is_enabled=True
        ).exists()

        cache.set(cache_key, result, timeout=300)
        return result

    @staticmethod
    def get_features(course) -> list[dict]:
        """
        Retrieves all registered active features along with their activation status and config for a course.
        """
        if not course:
            return []

        active_features = Feature.objects.filter(is_active=True)
        course_features_map = {
            cf.feature_id: cf for cf in CourseFeature.objects.filter(course=course).select_related('feature')
        }

        result = []
        for feature in active_features:
            cf = course_features_map.get(feature.id)
            is_enabled = cf.is_enabled if cf else False
            config = cf.config if cf else {}
            result.append({
                'id': str(feature.id),
                'code': feature.code,
                'name': feature.name,
                'description': feature.description,
                'category': feature.category,
                'scope': feature.scope,
                'frontend_key': feature.frontend_key or feature.code,
                'frontend_route': feature.frontend_route,
                'icon_key': feature.icon_key,
                'sort_order': feature.sort_order,
                'is_enabled': is_enabled,
                'config': config,
                'enabled_at': cf.enabled_at if cf else None,
                'disabled_at': cf.disabled_at if cf else None,
            })
        return result

    @staticmethod
    def get_feature_config(course, feature_code: str) -> dict:
        """
        Returns feature configuration JSON if enabled, otherwise empty dict.
        """
        try:
            cf = CourseFeature.objects.get(
                course=course,
                feature__code=feature_code,
                feature__is_active=True,
                is_enabled=True
            )
            return cf.config or {}
        except CourseFeature.DoesNotExist:
            return {}

    @staticmethod
    @transaction.atomic
    def enable_feature(course, feature_code: str, user=None, config: dict = None) -> CourseFeature:
        """
        Enables a feature for a course.
        """
        try:
            feature = Feature.objects.get(code=feature_code, is_active=True)
        except Feature.DoesNotExist:
            raise CubixSkillAPIException(
                f"Feature '{feature_code}' does not exist or is globally inactive.",
                code="FEATURE_NOT_FOUND",
                status_code=404
            )

        now = timezone.now()
        cf, created = CourseFeature.objects.get_or_create(
            course=course,
            feature=feature,
            defaults={
                'is_enabled': True,
                'config': config or {},
                'enabled_by': user,
                'enabled_at': now,
                'disabled_at': None
            }
        )

        if not created:
            cf.is_enabled = True
            if config is not None:
                cf.config = config
            cf.enabled_by = user
            cf.enabled_at = now
            cf.disabled_at = None
            cf.save()

        CourseFeatureService.invalidate_course_cache(course.id, feature_code)
        return cf

    @staticmethod
    @transaction.atomic
    def disable_feature(course, feature_code: str, user=None) -> CourseFeature:
        """
        Disables a feature for a course without destroying historical data.
        """
        try:
            feature = Feature.objects.get(code=feature_code)
        except Feature.DoesNotExist:
            raise CubixSkillAPIException(
                f"Feature '{feature_code}' does not exist.",
                code="FEATURE_NOT_FOUND",
                status_code=404
            )

        cf, created = CourseFeature.objects.get_or_create(
            course=course,
            feature=feature,
            defaults={
                'is_enabled': False,
                'disabled_at': timezone.now(),
                'enabled_by': user
            }
        )

        if not created and cf.is_enabled:
            cf.is_enabled = False
            cf.disabled_at = timezone.now()
            cf.save()

        CourseFeatureService.invalidate_course_cache(course.id, feature_code)
        return cf


class StudentFeatureService:
    """
    Service for resolving Student-level feature entitlements across courses.
    """

    @staticmethod
    def has_course_feature(student, course, feature_code: str) -> bool:
        """
        Checks if a student has access to a feature inside a specific course.
        Requires: Valid Student + Valid Enrollment in Course + Course Feature Enabled.
        """
        has_access, reason, _ = EnrollmentAccessService.can_access_course(student, course)
        if not has_access:
            return False

        return CourseFeatureService.has_feature(course, feature_code)

    @staticmethod
    def get_course_features(student, course) -> dict:
        """
        Returns a key-value dictionary of feature codes to boolean enablement for a specific course.
        Only returns features if student has valid enrollment in the course.
        Example: {"chat": True, "course_reports": False, "certificates": True}
        """
        has_access, _, _ = EnrollmentAccessService.can_access_course(student, course)
        if not has_access:
            return {}

        active_features = Feature.objects.filter(is_active=True)
        enabled_codes = set(
            CourseFeature.objects.filter(
                course=course,
                is_enabled=True,
                feature__is_active=True
            ).values_list('feature__code', flat=True)
        )

        return {feature.code: (feature.code in enabled_codes) for feature in active_features}

    @staticmethod
    def get_available_features(student) -> list[str]:
        """
        Returns distinct feature codes available to the student across ALL courses they are actively enrolled in.
        Useful for rendering student global navigation items.
        """
        if not student or not student.is_authenticated:
            return []

        # Find all active course IDs student is enrolled in
        from enrollments.models import Enrollment, EnrollmentStatus
        now = timezone.now()
        
        enrolled_course_ids = Enrollment.objects.filter(
            student=student,
            status=EnrollmentStatus.ACTIVE
        ).filter(
            Q(is_lifetime=True) | Q(access_expires_at__isnull=True) | Q(access_expires_at__gt=now)
        ).values_list('course_id', flat=True)

        if not enrolled_course_ids:
            return []

        # Return distinct feature codes enabled in any of those courses
        distinct_features = CourseFeature.objects.filter(
            course_id__in=enrolled_course_ids,
            is_enabled=True,
            feature__is_active=True
        ).values_list('feature__code', flat=True).distinct()

        return list(distinct_features)


class AcademyFeatureService:
    """
    Service for deriving Academy-level feature summaries from its Courses.
    Note: Academy Feature entitlement is derived, not primary source of truth.
    """

    @staticmethod
    def get_academy_used_features(academy) -> list[dict]:
        """
        Returns features enabled in at least one Course belonging to the given Academy,
        along with the count of courses enabling each feature.
        """
        if not academy:
            return []

        # Aggregate enabled features across courses belonging to the academy
        usage_counts = CourseFeature.objects.filter(
            course__academy=academy,
            is_enabled=True,
            feature__is_active=True
        ).values('feature__id', 'feature__code', 'feature__name', 'feature__category').annotate(
            enabled_course_count=Count('course', distinct=True)
        )

        return [
            {
                'feature_id': str(item['feature__id']),
                'code': item['feature__code'],
                'name': item['feature__name'],
                'category': item['feature__category'],
                'enabled_course_count': item['enabled_course_count']
            }
            for item in usage_counts
        ]
