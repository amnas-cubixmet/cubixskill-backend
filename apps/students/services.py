#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import logging
import re

from authentication.models import AuthTokenService, TokenType
from core.utils import CubixSkillAPIException
from django.db import transaction
from students.models import StudentProfile, StudentStatus
from users_roles.models import SystemRoleCode, User

logger = logging.getLogger(__name__)

#--------------------------------------------------------------
# Student Service Operations
#--------------------------------------------------------------

class StudentService:
    @staticmethod
    def _generate_unique_student_code(academy) -> str:
        academy_hex = academy.id.hex[:4].upper() if (academy and hasattr(academy, 'id') and academy.id) else "0000"
        prefix = f"CS-STU-{academy_hex}"
        
        count = StudentProfile.objects.filter(user__academy=academy).count() + 1
        code = f"{prefix}-{count:06d}"
        while StudentProfile.objects.filter(user__academy=academy, student_code=code).exists():
            count += 1
            code = f"{prefix}-{count:06d}"
        return code

    @staticmethod
    @transaction.atomic
    def create_student(academy, email: str, full_name: str, phone: str = '', created_by=None) -> StudentProfile:
        normalized_email = email.strip().lower()
        clean_name = full_name.strip()

        if User.objects.filter(email=normalized_email, academy=academy).exists():
            raise CubixSkillAPIException("User with this email already exists in this academy.", code="USER_EXISTS", status_code=400)

        # 1. Create User account
        user = User.objects.create_user(
            email=normalized_email,
            full_name=clean_name,
            phone=phone.strip(),
            role_code=SystemRoleCode.STUDENT,
            academy=academy,
            is_email_verified=False,
            password_setup_completed=False
        )

        # 2. Derive unique student_code safely
        student_code = StudentService._generate_unique_student_code(academy)

        # 3. Create StudentProfile with PENDING status for unverified account
        profile = StudentProfile.objects.create(
            user=user,
            student_code=student_code,
            display_name=clean_name,
            status=StudentStatus.PENDING
        )

        # 4. Generate token & send activation email
        try:
            raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
            from emails.services import send_student_activation_email
            send_student_activation_email(user=user, academy=academy, raw_token=raw_token)
        except Exception as err:
            logger.warning("Failed to send activation email to %s: %s", normalized_email, str(err))

        return profile

    @staticmethod
    @transaction.atomic
    def update_student(student_profile: StudentProfile, **kwargs) -> StudentProfile:
        user = student_profile.user
        if kwargs.get('full_name'):
            clean_name = kwargs['full_name'].strip()
            user.full_name = clean_name
            student_profile.display_name = clean_name
        if kwargs.get('email'):
            new_email = kwargs['email'].strip().lower()
            if User.objects.filter(email=new_email, academy=user.academy).exclude(id=user.id).exists():
                raise CubixSkillAPIException("Another user with this email already exists in this academy.", code="EMAIL_EXISTS", status_code=400)
            user.email = new_email
        if 'phone' in kwargs:
            user.phone = kwargs['phone'].strip()
        user.save()

        if kwargs.get('display_name'):
            student_profile.display_name = kwargs['display_name'].strip()
        if 'date_of_birth' in kwargs:
            student_profile.date_of_birth = kwargs['date_of_birth']
        if 'bio' in kwargs:
            student_profile.bio = kwargs['bio']
        if kwargs.get('status'):
            new_status = kwargs['status'].upper()
            student_profile.status = new_status
            if new_status in [StudentStatus.INACTIVE, StudentStatus.SUSPENDED, StudentStatus.ARCHIVED]:
                user.is_active = False
                user.save(update_fields=['is_active'])
            elif new_status in [StudentStatus.ACTIVE, StudentStatus.PENDING]:
                user.is_active = True
                user.save(update_fields=['is_active'])

        student_profile.save()
        return student_profile

    @staticmethod
    def resend_activation_email(student_profile: StudentProfile, academy=None) -> bool:
        user = student_profile.user
        if not user:
            raise CubixSkillAPIException("No user account attached to student profile.", code="NO_USER", status_code=400)
        target_academy = academy or getattr(user, 'academy', None)
        raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
        from emails.services import send_student_activation_email
        return send_student_activation_email(user=user, academy=target_academy, raw_token=raw_token)

    @staticmethod
    def update_status(student_profile: StudentProfile, new_status: str) -> StudentProfile:
        student_profile.status = new_status
        student_profile.save(update_fields=['status'])

        # Deactivate user login access if inactive or suspended
        if new_status in [StudentStatus.INACTIVE, StudentStatus.SUSPENDED, StudentStatus.ARCHIVED]:
            student_profile.user.is_active = False
            student_profile.user.save(update_fields=['is_active'])
        elif new_status in [StudentStatus.ACTIVE, StudentStatus.PENDING]:
            student_profile.user.is_active = True
            student_profile.user.save(update_fields=['is_active'])

        return student_profile

    @staticmethod
    def bulk_upload_students(academy, course_id: str, rows: list, created_by=None) -> dict:
        from courses.models import Course
        from enrollments.models import AccessType, Enrollment, EnrollmentSource
        from enrollments.services import EnrollmentService

        if not academy:
            raise CubixSkillAPIException("User is not associated with an Academy.", code="NO_ACADEMY", status_code=400)

        # Tenant-isolated course lookup
        try:
            course = Course.objects.get(id=course_id, academy=academy)
        except Course.DoesNotExist:
            if Course.objects.filter(id=course_id).exists():
                raise CubixSkillAPIException("Course does not belong to your academy.", code="ACADEMY_MISMATCH", status_code=403)
            raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

        email_regex = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

        row_results = []
        valid_count = 0
        invalid_count = 0
        duplicate_count = 0
        enrolled_count = 0

        for idx, row in enumerate(rows, start=1):
            sid = transaction.savepoint()
            try:
                raw_name = str(row.get('full_name') or row.get('name') or '').strip()
                raw_email = str(row.get('email') or '').strip().lower()
                raw_phone = str(row.get('phone') or '').strip()

                if not raw_email or not email_regex.match(raw_email):
                    invalid_count += 1
                    transaction.savepoint_rollback(sid)
                    row_results.append({
                        "row": idx,
                        "name": raw_name or "Unknown",
                        "email": raw_email,
                        "student_code": None,
                        "student_user_id": None,
                        "student_profile_id": None,
                        "student_created": False,
                        "enrollment_created": False,
                        "activation_email_sent": False,
                        "status": "invalid",
                        "errorMessage": "Valid email is required"
                    })
                    continue

                valid_count += 1

                # Check if student exists in academy
                existing_user = User.objects.filter(email=raw_email, academy=academy).first()
                student_created = False
                activation_email_sent = False

                if existing_user:
                    user = existing_user
                    profile = getattr(user, 'student_profile', None)
                    if not profile:
                        code = StudentService._generate_unique_student_code(academy)
                        profile = StudentProfile.objects.create(
                            user=user,
                            student_code=code,
                            display_name=raw_name or user.full_name,
                            status=StudentStatus.ACTIVE if user.password_setup_completed else StudentStatus.PENDING
                        )
                else:
                    display_name = raw_name if raw_name else raw_email.split('@')[0].capitalize()
                    user = User.objects.create_user(
                        email=raw_email,
                        full_name=display_name,
                        phone=raw_phone,
                        role_code=SystemRoleCode.STUDENT,
                        academy=academy,
                        is_email_verified=False,
                        password_setup_completed=False
                    )
                    code = StudentService._generate_unique_student_code(academy)
                    profile = StudentProfile.objects.create(
                        user=user,
                        student_code=code,
                        display_name=display_name,
                        status=StudentStatus.PENDING
                    )
                    student_created = True

                    try:
                        raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                        from emails.services import send_student_activation_email
                        send_student_activation_email(user=user, academy=academy, raw_token=raw_token)
                        activation_email_sent = True
                    except Exception as email_err:
                        logger.warning("Failed to send activation email to %s: %s", raw_email, str(email_err))
                        activation_email_sent = False

                # Check existing enrollment
                already_enrolled = Enrollment.objects.filter(student=user, course=course).exists()
                if already_enrolled:
                    duplicate_count += 1
                    transaction.savepoint_commit(sid)
                    row_results.append({
                        "row": idx,
                        "name": profile.display_name,
                        "email": user.email,
                        "student_code": profile.student_code,
                        "student_user_id": str(user.id),
                        "student_profile_id": str(profile.id),
                        "student_created": student_created,
                        "enrollment_created": False,
                        "activation_email_sent": activation_email_sent,
                        "status": "duplicate",
                        "errorMessage": "Already enrolled — skipped to prevent double enrollment"
                    })
                else:
                    EnrollmentService.enroll_student(
                        student=user,
                        course=course,
                        access_type=AccessType.FULL,
                        source=EnrollmentSource.IMPORT,
                        created_by=created_by
                    )
                    enrolled_count += 1
                    transaction.savepoint_commit(sid)
                    row_results.append({
                        "row": idx,
                        "name": profile.display_name,
                        "email": user.email,
                        "student_code": profile.student_code,
                        "student_user_id": str(user.id),
                        "student_profile_id": str(profile.id),
                        "student_created": student_created,
                        "enrollment_created": True,
                        "activation_email_sent": activation_email_sent,
                        "status": "valid",
                        "message": "Enrolled successfully"
                    })
            except Exception as row_err:
                transaction.savepoint_rollback(sid)
                logger.exception("Error processing bulk upload row %d: %s", idx, str(row_err))
                row_results.append({
                    "row": idx,
                    "name": raw_name if 'raw_name' in locals() and raw_name else "Unknown",
                    "email": raw_email if 'raw_email' in locals() and raw_email else "",
                    "student_code": None,
                    "student_user_id": None,
                    "student_profile_id": None,
                    "student_created": False,
                    "enrollment_created": False,
                    "activation_email_sent": False,
                    "status": "invalid",
                    "errorMessage": getattr(row_err, 'detail', None) or str(row_err) or "Failed to process row"
                })

        return {
            "total_rows": len(rows),
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "duplicate_count": duplicate_count,
            "enrolled_count": enrolled_count,
            "results": row_results
        }


