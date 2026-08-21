import logging
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from django.core.cache import cache
from core.utils import CubixSkillAPIException
from enrollments.services import EnrollmentAccessService
from features.models import Feature, CourseFeature

logger = logging.getLogger(__name__)

DEFAULT_FEATURES = [
    {
        'code': 'LIVE_SESSIONS',
        'name': 'Live Sessions',
        'description': 'Schedule and manage live classes and interactive video sessions.',
        'category': 'Live Learning',
        'icon_key': 'Video',
        'sort_order': 1,
    },
    {
        'code': 'QUIZZES',
        'name': 'Quizzes & Assessments',
        'description': 'Create quizzes, mock tests, and automated assessments.',
        'category': 'Assessment',
        'icon_key': 'HelpCircle',
        'sort_order': 2,
    },
    {
        'code': 'ASSIGNMENTS',
        'name': 'Assignments & Submissions',
        'description': 'Manage student assignment tasks, submissions, and grading.',
        'category': 'Assessment',
        'icon_key': 'FileText',
        'sort_order': 3,
    },
    {
        'code': 'DISCUSSIONS',
        'name': 'Course Discussions',
        'description': 'Interactive Q&A discussion board and course chat room.',
        'category': 'Community',
        'icon_key': 'MessageSquare',
        'sort_order': 4,
    },
    {
        'code': 'ANNOUNCEMENTS',
        'name': 'Course Announcements',
        'description': 'Broadcast official updates and notifications to enrolled students.',
        'category': 'Communication',
        'icon_key': 'Bell',
        'sort_order': 5,
    },
    {
        'code': 'CERTIFICATES',
        'name': 'Completion Certificates',
        'description': 'Issue digital completion certificates automatically upon course finish.',
        'category': 'Completion',
        'icon_key': 'Award',
        'sort_order': 6,
    },
    {
        'code': 'COUPONS',
        'name': 'Promotional Coupons',
        'description': 'Create promotional discount codes for course checkouts.',
        'category': 'Commerce',
        'icon_key': 'Tag',
        'sort_order': 7,
    },
    {
        'code': 'FEES',
        'name': 'Student Fee Collection',
        'description': 'Manage student installment plans, payment collection, and ledgers.',
        'category': 'Commerce',
        'icon_key': 'Wallet',
        'sort_order': 8,
    },
    {
        'code': 'COURSE_RESOURCES',
        'name': 'Resource Downloads',
        'description': 'Allow students to download supplementary files and attachments.',
        'category': 'Content',
        'icon_key': 'Download',
        'sort_order': 9,
    },
    {
        'code': 'COURSE_REPORTS',
        'name': 'Analytics & Reports',
        'description': 'Track student completion metrics, progress, and performance.',
        'category': 'Analytics',
        'icon_key': 'BarChart2',
        'sort_order': 10,
    },
]

DEFAULT_CODES = {f['code'] for f in DEFAULT_FEATURES}


class CourseFeatureService:

    @staticmethod
    def ensure_default_features():
        """
        Seeds canonical features if none exist.
        """
        for item in DEFAULT_FEATURES:
            Feature.objects.get_or_create(
                code=item['code'],
                defaults={
                    'name': item['name'],
                    'description': item['description'],
                    'category': item['category'],
                    'icon_key': item['icon_key'],
                    'sort_order': item['sort_order'],
                    'is_active': True,
                    'frontend_key': item['code'],
                }
            )

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
    def is_feature_enabled_for_academy(academy, feature_code: str) -> bool:
        if not academy:
            return True
        return True

    @staticmethod
    def has_feature(course, feature_code: str) -> bool:
        """
        Returns True if the feature is globally active AND academy enabled AND course enabled.
        """
        if not course or not feature_code:
            return False

        cache_key = CourseFeatureService.get_cache_key(course.id, feature_code)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        feat = Feature.objects.filter(code=feature_code, is_active=True).first()
        if not feat:
            cache.set(cache_key, False, timeout=300)
            return False

        academy_enabled = CourseFeatureService.is_feature_enabled_for_academy(course.academy, feature_code)
        if not academy_enabled:
            cache.set(cache_key, False, timeout=300)
            return False

        cf = CourseFeature.objects.filter(course=course, feature=feat).first()
        if cf is not None:
            result = cf.is_enabled
        else:
            result = (feature_code in DEFAULT_CODES)

        cache.set(cache_key, result, timeout=300)
        return result

    @staticmethod
    def get_features(course) -> list[dict]:
        if not course:
            return []

        CourseFeatureService.ensure_default_features()

        active_features = Feature.objects.filter(is_active=True).order_by('sort_order', 'name')
        course_features_map = {
            cf.feature_id: cf for cf in CourseFeature.objects.filter(course=course).select_related('feature')
        }

        result = []
        for feature in active_features:
            cf = course_features_map.get(feature.id)
            academy_enabled = CourseFeatureService.is_feature_enabled_for_academy(course.academy, feature.code)
            course_enabled = cf.is_enabled if cf is not None else (feature.code in DEFAULT_CODES)
            effective_enabled = academy_enabled and course_enabled
            can_configure = academy_enabled

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
                'academy_enabled': academy_enabled,
                'course_enabled': course_enabled,
                'effective_enabled': effective_enabled,
                'is_enabled': effective_enabled,
                'can_configure': can_configure,
                'config': cf.config if cf else {},
                'enabled_at': cf.enabled_at if cf else None,
                'disabled_at': cf.disabled_at if cf else None,
            })
        return result

    @staticmethod
    def get_feature_config(course, feature_code: str) -> dict:
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
        CourseFeatureService.ensure_default_features()
        try:
            feature = Feature.objects.get(code=feature_code, is_active=True)
        except Feature.DoesNotExist:
            raise CubixSkillAPIException(
                f"Feature '{feature_code}' does not exist or is globally inactive.",
                code="FEATURE_NOT_FOUND",
                status_code=404
            )

        if not CourseFeatureService.is_feature_enabled_for_academy(course.academy, feature_code):
            raise CubixSkillAPIException(
                f"Feature '{feature_code}' is not included in your Academy plan.",
                code="ACADEMY_FEATURE_DISABLED",
                status_code=403
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
        CourseFeatureService.ensure_default_features()
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

    @staticmethod
    @transaction.atomic
    def save_bulk_features(course, features_dict: dict, user=None):
        CourseFeatureService.ensure_default_features()
        if not isinstance(features_dict, dict):
            return CourseFeatureService.get_features(course)

        for code, is_enabled in features_dict.items():
            if not isinstance(code, str):
                continue
            code_upper = code.strip().upper()
            bool_enabled = bool(is_enabled)
            if bool_enabled:
                try:
                    CourseFeatureService.enable_feature(course, code_upper, user=user)
                except CubixSkillAPIException as e:
                    if e.code == "ACADEMY_FEATURE_DISABLED":
                        continue
                    raise
            else:
                try:
                    CourseFeatureService.disable_feature(course, code_upper, user=user)
                except CubixSkillAPIException:
                    continue

        CourseFeatureService.invalidate_course_cache(course.id)
        return CourseFeatureService.get_features(course)


class StudentFeatureService:

    @staticmethod
    def has_course_feature(student, course, feature_code: str) -> bool:
        has_access, reason, _ = EnrollmentAccessService.can_access_course(student, course)
        if not has_access:
            return False
        return CourseFeatureService.has_feature(course, feature_code)

    @staticmethod
    def get_course_features(student, course) -> dict:
        has_access, _, _ = EnrollmentAccessService.can_access_course(student, course)
        if not has_access:
            return {}

        CourseFeatureService.ensure_default_features()
        active_features = Feature.objects.filter(is_active=True)
        return {f.code: CourseFeatureService.has_feature(course, f.code) for f in active_features}

    @staticmethod
    def get_available_features(student) -> list[str]:
        if not student or not student.is_authenticated:
            return []

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

        CourseFeatureService.ensure_default_features()
        active_features = Feature.objects.filter(is_active=True)
        available = []
        for feat in active_features:
            for c_id in enrolled_course_ids:
                from courses.models import Course
                try:
                    c = Course.objects.get(id=c_id)
                    if CourseFeatureService.has_feature(c, feat.code):
                        available.append(feat.code)
                        break
                except Course.DoesNotExist:
                    continue
        return available


class AcademyFeatureService:

    @staticmethod
    def get_academy_used_features(academy) -> list[dict]:
        if not academy:
            return []

        CourseFeatureService.ensure_default_features()
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
