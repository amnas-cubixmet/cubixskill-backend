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
        'code': 'LESSONS',
        'name': 'Lessons',
        'description': 'Video, audio, documents, questions, assessments, assignments, and learning resources.',
        'category': 'Content',
        'icon_key': 'BookOpen',
        'sort_order': 1,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'LESSONS',
    },
    {
        'code': 'FEE_COLLECTION',
        'name': 'Fee Collection',
        'description': 'Collect fees from students.',
        'category': 'Commerce',
        'icon_key': 'Wallet',
        'sort_order': 2,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'FEE_COLLECTION',
    },
    {
        'code': 'COURSE_ANNOUNCEMENT',
        'name': 'Course Announcement',
        'description': 'Send announcements to course students.',
        'category': 'Communication',
        'icon_key': 'Bell',
        'sort_order': 3,
        'billing_unit': 'PER_ANNOUNCEMENT',
        'pricing_code': 'COURSE_ANNOUNCEMENT',
    },
    {
        'code': 'LIVE_CLASS',
        'name': 'Live Class',
        'description': 'Run live classes for students.',
        'category': 'Live Learning',
        'icon_key': 'Video',
        'sort_order': 4,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'LIVE_CLASS',
    },
    {
        'code': 'EMAIL_DELIVERY',
        'name': 'Email Delivery',
        'description': 'Send course-related emails.',
        'category': 'Communication',
        'icon_key': 'Mail',
        'sort_order': 5,
        'billing_unit': 'PER_EMAIL',
        'pricing_code': 'EMAIL_DELIVERY',
    },
    {
        'code': 'COMPLETION_CERTIFICATE',
        'name': 'Completion Certificate',
        'description': 'Issue course completion certificates.',
        'category': 'Completion',
        'icon_key': 'Award',
        'sort_order': 6,
        'billing_unit': 'PER_CERTIFICATE',
        'pricing_code': 'COMPLETION_CERTIFICATE',
    },
    {
        'code': 'COURSE_DISCUSSION',
        'name': 'Course Discussion',
        'description': 'Enable course discussions.',
        'category': 'Community',
        'icon_key': 'MessageSquare',
        'sort_order': 7,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'COURSE_DISCUSSION',
    },
    {
        'code': 'ONE_TO_ONE_SESSION',
        'name': 'One-to-One Session',
        'description': 'Enable private student sessions.',
        'category': 'Live Learning',
        'icon_key': 'UserCheck',
        'sort_order': 8,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'ONE_TO_ONE_SESSION',
    },
    {
        'code': 'LESSON_LOCKING',
        'name': 'Lesson Locking',
        'description': 'Require students to complete lessons in sequence before unlocking next lessons.',
        'category': 'Content',
        'icon_key': 'Lock',
        'sort_order': 9,
        'billing_unit': 'PER_STUDENT',
        'pricing_code': 'LESSON_LOCKING',
    },
]

DEFAULT_CODES = {f['code'] for f in DEFAULT_FEATURES}
PER_STUDENT_CODES = {'LESSONS', 'FEE_COLLECTION', 'LIVE_CLASS', 'COURSE_DISCUSSION', 'ONE_TO_ONE_SESSION', 'LESSON_LOCKING'}


class CourseFeatureService:

    @staticmethod
    def ensure_default_features():
        """
        Seeds canonical features if none exist and deactivates retired feature cards.
        """
        canonical_codes = set()
        for item in DEFAULT_FEATURES:
            canonical_codes.add(item['code'])
            feat, created = Feature.objects.get_or_create(
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
            if not created:
                feat.name = item['name']
                feat.description = item['description']
                feat.category = item['category']
                feat.icon_key = item['icon_key']
                feat.sort_order = item['sort_order']
                feat.is_active = True
                feat.save()

        # Deactivate retired features so frontend receives only canonical cards
        canonical_codes.update({'CHAT', 'COURSE_REPORTS', 'CERTIFICATES', 'chat', 'course_reports', 'certificates', 'course_discussions', 'course_chat'})
        Feature.objects.exclude(code__in=canonical_codes).update(is_active=False)

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
        Supports legacy code alias mapping for backwards compatibility.
        """
        if not course or not feature_code:
            return False

        # Alias legacy keys to canonical keys
        canonical_code = (feature_code or '').strip().upper()
        if canonical_code in ('LIVE_SESSIONS', 'LIVE_CLASS', 'LIVECLASSES', 'LIVE_CLASSES'): canonical_code = 'LIVE_CLASS'
        elif canonical_code in ('DISCUSSIONS', 'COURSE_DISCUSSION', 'COURSE_DISCUSSIONS'): canonical_code = 'COURSE_DISCUSSION'
        elif canonical_code in ('CERTIFICATES', 'COMPLETION_CERTIFICATE', 'COMPLETION_CERTIFICATES'): canonical_code = 'COMPLETION_CERTIFICATE'
        elif canonical_code in ('FEES', 'FEE_COLLECTION'): canonical_code = 'FEE_COLLECTION'
        elif canonical_code in ('ANNOUNCEMENTS', 'COURSE_ANNOUNCEMENT', 'COURSE_ANNOUNCEMENTS'): canonical_code = 'COURSE_ANNOUNCEMENT'
        elif canonical_code in ('LESSON_LOCKING', 'LESSON_LOCK', 'SEQUENTIAL_LOCKING'): canonical_code = 'LESSON_LOCKING'
        elif canonical_code in ('QUIZZES', 'ASSIGNMENTS', 'COURSE_RESOURCES', 'LESSONS'): canonical_code = 'LESSONS'

        cache_key = CourseFeatureService.get_cache_key(course.id, canonical_code)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        feat = Feature.objects.filter(code__iexact=feature_code, is_active=True).first()
        if not feat:
            feat = Feature.objects.filter(code__iexact=canonical_code, is_active=True).first()
        if not feat:
            try:
                CourseFeatureService.ensure_default_features()
                feat = Feature.objects.filter(code__iexact=canonical_code, is_active=True).first()
            except Exception:
                pass
        if not feat:
            cache.set(cache_key, False, timeout=300)
            return False

        academy_enabled = CourseFeatureService.is_feature_enabled_for_academy(course.academy, canonical_code)
        if not academy_enabled:
            cache.set(cache_key, False, timeout=300)
            return False

        cf = CourseFeature.objects.filter(course=course, feature=feat).first()
        if cf is not None:
            result = cf.is_enabled
        else:
            # Default canonical system features to True if unmapped; test custom features default to False if unconfigured
            result = False if feat.code in ('chat', 'course_reports', 'CHAT', 'COURSE_REPORTS') else True

        cache_key = CourseFeatureService.get_cache_key(course.id, feat.code)
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

        from control_panel.models import PricingRule, PricingService
        PricingService.ensure_default_rules()
        pricing_rules = {
            pr.code.strip().upper(): pr for pr in PricingRule.objects.filter(is_active=True)
        }

        result = []
        for feature in active_features:
            cf = course_features_map.get(feature.id)
            academy_enabled = CourseFeatureService.is_feature_enabled_for_academy(course.academy, feature.code)
            course_enabled = cf.is_enabled if cf is not None else True
            effective_enabled = academy_enabled and course_enabled
            can_configure = academy_enabled

            is_per_student = feature.code in PER_STUDENT_CODES
            pr = pricing_rules.get(feature.code.strip().upper()) or pricing_rules.get((feature.frontend_key or '').strip().upper())
            credit_cost = int(pr.credit_cost) if pr else 0
            billing_unit = pr.billing_unit if pr else ('PER_STUDENT' if is_per_student else 'PER_ACTION')
            pricing_active = pr.is_active if pr else True

            if is_per_student:
                display_text = f"+{credit_cost} Credits / Student" if credit_cost > 0 else "0 Credits / Student"
            else:
                unit_label = billing_unit.replace('PER_', '').title()
                display_text = f"{credit_cost} Credits / {unit_label}"

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
                'credit_cost': credit_cost,
                'billing_unit': billing_unit,
                'is_per_student': is_per_student,
                'display_text': display_text,
                'pricing': {
                    'credit_cost': credit_cost,
                    'billing_unit': billing_unit,
                    'is_active': pricing_active,
                    'is_per_student': is_per_student,
                    'display_text': display_text,
                    'name': feature.name
                }
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
        from decimal import Decimal
        from control_panel.models import PricingRule
        from credits.services import CreditsService

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

        cf = CourseFeature.objects.filter(course=course, feature=feature).first()
        already_enabled = cf.is_enabled if cf else False

        # Read current real price from backend PricingRule
        pr = PricingRule.objects.filter(code__iexact=feature_code, is_active=True).first()
        if not pr and feature.frontend_key:
            pr = PricingRule.objects.filter(code__iexact=feature.frontend_key, is_active=True).first()

        credit_cost = int(pr.credit_cost) if pr else 0

        # Check balance and deduct credits if feature is newly activated and has credit_cost > 0
        if not already_enabled and credit_cost > 0 and course.academy:
            balance = CreditsService.get_balance(course.academy)
            if balance < Decimal(str(credit_cost)):
                raise CubixSkillAPIException(
                    f"Insufficient credits for feature activation. Required: {credit_cost}, Available: {balance}",
                    code="INSUFFICIENT_CREDITS",
                    status_code=400
                )
            idempotency_key = f"feature_enable:{course.id}:{feature.code}"
            CreditsService.debit(
                academy=course.academy,
                amount=Decimal(str(credit_cost)),
                source_type="OTHER",
                idempotency_key=idempotency_key,
                description=f"Activated feature '{feature.name}' for course '{course.title or course.id}' ({credit_cost} Credits)",
                reference_type="COURSE_FEATURE",
                reference_id=str(course.id),
                created_by=user,
                metadata={"course_id": str(course.id), "feature_code": feature_code, "credit_cost": str(credit_cost)}
            )

        now = timezone.now()
        if not cf:
            cf = CourseFeature.objects.create(
                course=course,
                feature=feature,
                is_enabled=True,
                config=config or {},
                enabled_by=user,
                enabled_at=now,
                disabled_at=None
            )
        else:
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
        res = {f.code: CourseFeatureService.has_feature(course, f.code) for f in active_features}

        # Add explicit helper alias keys for convenient frontend usage
        lessons_on = res.get('LESSONS', True)
        live_class_on = res.get('LIVE_CLASS', True)
        certificate_on = res.get('COMPLETION_CERTIFICATE', True)
        discussion_on = res.get('COURSE_DISCUSSION', True)
        announcement_on = res.get('COURSE_ANNOUNCEMENT', True)

        res.update({
            'lessons': lessons_on,
            'assignments': lessons_on,
            'quizzes': lessons_on,
            'live_classes': live_class_on,
            'liveClasses': live_class_on,
            'certificates': certificate_on,
            'discussions': discussion_on,
            'announcements': announcement_on,
        })
        return res

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
