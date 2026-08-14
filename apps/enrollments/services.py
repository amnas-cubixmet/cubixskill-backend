from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from core.utils import CubixSkillAPIException
from enrollments.models import (
    Enrollment,
    AccessType,
    EnrollmentStatus,
    EnrollmentSource,
    EnrollmentAccessPeriod,
    EnrollmentEvent,
    EnrollmentEventType,
)
from learning_progress.models import CourseProgress, ProgressStatus

#--------------------------------------------------------------
# Enrollment Access Service
#--------------------------------------------------------------

class EnrollmentAccessService:
    @staticmethod
    def can_access_course(user, course) -> tuple[bool, str, str]:
        """
        Determines whether a user has valid, active entitlement to a course.
        Returns: (has_access: bool, reason_code: str, message: str)
        """
        if not user or not user.is_authenticated:
            return False, "UNAUTHENTICATED", "Authentication required."

        # Super admin bypass
        if getattr(user, 'is_superuser', False) or getattr(user, 'role_code', '') == 'SUPER_ADMIN':
            return True, "SUPER_ADMIN", "Super Admin access granted."

        # Tenant isolation check
        user_academy_id = getattr(user, 'academy_id', None)
        if user_academy_id and course.academy_id and user_academy_id != course.academy_id:
            return False, "CROSS_ACADEMY_RESTRICTED", "User does not belong to the academy owning this course."

        try:
            enrollment = Enrollment.objects.get(student=user, course=course)
        except Enrollment.DoesNotExist:
            return False, "NO_ENROLLMENT", "User is not enrolled in this course."

        if not enrollment.is_currently_valid():
            return False, "ENROLLMENT_INACTIVE", f"Enrollment is in {enrollment.status} state or outside access window."

        return True, "GRANTED", "Access granted."

    @staticmethod
    def can_access_lesson(user, lesson) -> tuple[bool, str, str]:
        """
        Determines whether a user can access a specific lesson.
        Checks course entitlement first, then validates demo restrictions.
        """
        course = lesson.module.course
        has_course_access, reason, msg = EnrollmentAccessService.can_access_course(user, course)
        if not has_course_access:
            return False, reason, msg

        # Super admin check
        if getattr(user, 'is_superuser', False) or getattr(user, 'role_code', '') == 'SUPER_ADMIN':
            return True, "SUPER_ADMIN", "Super Admin access granted."

        enrollment = Enrollment.objects.get(student=user, course=course)
        if enrollment.access_type == AccessType.DEMO and not lesson.is_demo:
            return False, "DEMO_RESTRICTED", "Demo enrollment only grants access to demo-enabled lessons."

        return True, "GRANTED", "Access granted."

# --------------------------------------------------------------
# Enrollment Core Service
# Central service for creating and changing course enrollment access.
# Responsible for preserving enrollment history and enforcing Demo/Full
# transition rules, extension, suspension, and revocation.
# --------------------------------------------------------------

class EnrollmentService:
    @staticmethod
    @transaction.atomic
    def enroll_student(
        student,
        course,
        access_type: str = AccessType.FULL,
        source: str = EnrollmentSource.PURCHASE,
        source_reference: str = '',
        is_lifetime: bool = True,
        access_starts_at=None,
        access_expires_at=None,
        created_by=None
    ) -> Enrollment:
        """
        Primary entry point for student enrollment. Enforces academy matching and creates/updates enrollment.
        """
        # Validate Academy boundary
        if getattr(student, 'academy_id', None) and course.academy_id:
            if student.academy_id != course.academy_id:
                raise CubixSkillAPIException(
                    "Student and Course must belong to the same Academy.",
                    code="CROSS_ACADEMY_ENROLLMENT_FORBIDDEN",
                    status_code=400
                )

        now = timezone.now()
        starts_at = access_starts_at or now

        enrollment, created = Enrollment.objects.select_for_update().get_or_create(
            student=student,
            course=course,
            defaults={
                'access_type': access_type,
                'status': EnrollmentStatus.ACTIVE,
                'source': source,
                'source_reference': source_reference,
                'enrolled_at': now,
                'access_starts_at': starts_at,
                'access_expires_at': access_expires_at if not is_lifetime else None,
                'is_lifetime': is_lifetime,
                'created_by': created_by
            }
        )

        if created:
            # Create Initial Access Period & Event
            EnrollmentAccessPeriod.objects.create(
                enrollment=enrollment,
                access_type=access_type,
                starts_at=starts_at,
                expires_at=access_expires_at if not is_lifetime else None,
                reason=f"Initial enrollment via {source}",
                granted_by=created_by,
                source_reference=source_reference
            )
            EnrollmentEvent.objects.create(
                enrollment=enrollment,
                event_type=EnrollmentEventType.CREATED,
                previous_status='',
                new_status=EnrollmentStatus.ACTIVE,
                performed_by=created_by,
                reason=f"Enrolled with {access_type} access via {source}",
                metadata={'source': source, 'access_type': access_type}
            )
        else:
            # Re-activate or update if inactive/upgrading
            prev_status = enrollment.status
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.access_type = access_type
            enrollment.is_lifetime = is_lifetime
            enrollment.access_starts_at = starts_at
            if not is_lifetime and access_expires_at:
                enrollment.access_expires_at = access_expires_at
            if source_reference:
                enrollment.source_reference = source_reference
            enrollment.save()

            EnrollmentEvent.objects.create(
                enrollment=enrollment,
                event_type=EnrollmentEventType.ACTIVATED if prev_status != EnrollmentStatus.ACTIVE else EnrollmentEventType.EXTENDED,
                previous_status=prev_status,
                new_status=EnrollmentStatus.ACTIVE,
                performed_by=created_by,
                reason=f"Enrollment updated to {access_type} access",
                metadata={'source': source, 'access_type': access_type}
            )

        # Initialize CourseProgress
        CourseProgress.objects.get_or_create(
            student=student,
            course=course,
            enrollment=enrollment,
            defaults={
                'total_lessons': 0,
                'status': ProgressStatus.NOT_STARTED
            }
        )

        return enrollment

    @staticmethod
    def grant_demo_access(student, course, duration_days: int = 5, source: str = EnrollmentSource.DEMO, created_by=None) -> Enrollment:
        now = timezone.now()
        expires_at = now + timedelta(days=duration_days)
        return EnrollmentService.enroll_student(
            student=student,
            course=course,
            access_type=AccessType.DEMO,
            source=source,
            is_lifetime=False,
            access_starts_at=now,
            access_expires_at=expires_at,
            created_by=created_by
        )

    @staticmethod
    def grant_full_access(
        student,
        course,
        is_lifetime: bool = True,
        access_expires_at=None,
        source: str = EnrollmentSource.PURCHASE,
        source_reference: str = '',
        created_by=None
    ) -> Enrollment:
        return EnrollmentService.enroll_student(
            student=student,
            course=course,
            access_type=AccessType.FULL,
            source=source,
            source_reference=source_reference,
            is_lifetime=is_lifetime,
            access_expires_at=access_expires_at,
            created_by=created_by
        )

    @staticmethod
    @transaction.atomic
    def upgrade_demo_to_full(enrollment: Enrollment, is_lifetime: bool = True, access_expires_at=None, source_reference: str = '', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        now = timezone.now()

        enrollment.access_type = AccessType.FULL
        enrollment.status = EnrollmentStatus.ACTIVE
        enrollment.is_lifetime = is_lifetime
        enrollment.access_starts_at = now
        enrollment.access_expires_at = access_expires_at if not is_lifetime else None
        if source_reference:
            enrollment.source_reference = source_reference
        enrollment.save()

        # Log new period
        EnrollmentAccessPeriod.objects.create(
            enrollment=enrollment,
            access_type=AccessType.FULL,
            starts_at=now,
            expires_at=access_expires_at if not is_lifetime else None,
            reason="Upgraded from DEMO to FULL access",
            granted_by=performed_by,
            source_reference=source_reference
        )

        # Log event
        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.UPGRADED_TO_FULL,
            previous_status=prev_status,
            new_status=EnrollmentStatus.ACTIVE,
            performed_by=performed_by,
            reason="Upgraded enrollment to FULL access",
            metadata={'is_lifetime': is_lifetime}
        )

        return enrollment

    @staticmethod
    @transaction.atomic
    def extend_access(enrollment: Enrollment, additional_days: int = None, new_expiry_date=None, reason: str = '', performed_by=None) -> Enrollment:
        now = timezone.now()
        current_expiry = enrollment.access_expires_at or now

        if additional_days:
            new_expiry = current_expiry + timedelta(days=additional_days)
        elif new_expiry_date:
            new_expiry = new_expiry_date
        else:
            raise CubixSkillAPIException("Must specify additional_days or new_expiry_date.", code="INVALID_EXTENSION_PARAM", status_code=400)

        enrollment.access_expires_at = new_expiry
        enrollment.is_lifetime = False
        if enrollment.status == EnrollmentStatus.EXPIRED:
            enrollment.status = EnrollmentStatus.ACTIVE
        enrollment.save()

        EnrollmentAccessPeriod.objects.create(
            enrollment=enrollment,
            access_type=enrollment.access_type,
            starts_at=now,
            expires_at=new_expiry,
            reason=reason or f"Extended access to {new_expiry}",
            granted_by=performed_by
        )

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.EXTENDED,
            previous_status=enrollment.status,
            new_status=EnrollmentStatus.ACTIVE,
            performed_by=performed_by,
            reason=reason or f"Access extended to {new_expiry}",
            metadata={'new_expiry': new_expiry.isoformat()}
        )

        return enrollment

    @staticmethod
    @transaction.atomic
    def suspend_enrollment(enrollment: Enrollment, reason: str = '', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        enrollment.status = EnrollmentStatus.SUSPENDED
        enrollment.save(update_fields=['status', 'updated_at'])

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.SUSPENDED,
            previous_status=prev_status,
            new_status=EnrollmentStatus.SUSPENDED,
            performed_by=performed_by,
            reason=reason or "Enrollment suspended by admin"
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def resume_enrollment(enrollment: Enrollment, reason: str = '', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        enrollment.status = EnrollmentStatus.ACTIVE
        enrollment.save(update_fields=['status', 'updated_at'])

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.RESUMED,
            previous_status=prev_status,
            new_status=EnrollmentStatus.ACTIVE,
            performed_by=performed_by,
            reason=reason or "Enrollment resumed by admin"
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def revoke_enrollment(enrollment: Enrollment, reason: str = '', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        enrollment.status = EnrollmentStatus.REVOKED
        enrollment.save(update_fields=['status', 'updated_at'])

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.REVOKED,
            previous_status=prev_status,
            new_status=EnrollmentStatus.REVOKED,
            performed_by=performed_by,
            reason=reason or "Enrollment revoked by admin"
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def cancel_enrollment(enrollment: Enrollment, reason: str = '', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        enrollment.status = EnrollmentStatus.CANCELLED
        enrollment.save(update_fields=['status', 'updated_at'])

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.CANCELLED,
            previous_status=prev_status,
            new_status=EnrollmentStatus.CANCELLED,
            performed_by=performed_by,
            reason=reason or "Enrollment cancelled"
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def expire_enrollment(enrollment: Enrollment, reason: str = 'Access period expired', performed_by=None) -> Enrollment:
        prev_status = enrollment.status
        enrollment.status = EnrollmentStatus.EXPIRED
        enrollment.save(update_fields=['status', 'updated_at'])

        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            event_type=EnrollmentEventType.EXPIRED,
            previous_status=prev_status,
            new_status=EnrollmentStatus.EXPIRED,
            performed_by=performed_by,
            reason=reason
        )
        return enrollment

    @staticmethod
    def bulk_enroll(students, course, access_type: str = AccessType.FULL, is_lifetime: bool = True, access_expires_at=None, created_by=None) -> dict:
        successful = []
        failed = []

        for student in students:
            try:
                enrollment = EnrollmentService.enroll_student(
                    student=student,
                    course=course,
                    access_type=access_type,
                    source=EnrollmentSource.MANUAL,
                    is_lifetime=is_lifetime,
                    access_expires_at=access_expires_at,
                    created_by=created_by
                )
                successful.append({
                    'student_id': str(student.id),
                    'enrollment_id': str(enrollment.id),
                    'status': enrollment.status
                })
            except Exception as e:
                failed.append({
                    'student_id': str(student.id),
                    'error': str(e)
                })

        return {
            'successful_count': len(successful),
            'failed_count': len(failed),
            'successful': successful,
            'failed': failed
        }
