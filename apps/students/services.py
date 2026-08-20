#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.db import transaction
from students.models import StudentProfile, StudentStatus
from users_roles.models import User, SystemRoleCode
from authentication.tasks import send_email_task
from authentication.models import AuthTokenService, TokenType
from core.utils import CubixSkillAPIException

#--------------------------------------------------------------
# Student Service Operations
#--------------------------------------------------------------

class StudentService:
    @staticmethod
    @transaction.atomic
    def create_student(academy, email: str, full_name: str, phone: str = '', created_by=None) -> StudentProfile:
        if User.objects.filter(email=email, academy=academy).exists():
            raise CubixSkillAPIException("User with this email already exists in this academy.", code="USER_EXISTS")

        # 1. Create User account
        user = User.objects.create_user(
            email=email,
            full_name=full_name,
            phone=phone,
            role_code=SystemRoleCode.STUDENT,
            academy=academy,
            is_email_verified=False,
            password_setup_completed=False
        )

        # 2. Derive unique student_code
        count = StudentProfile.objects.filter(user__academy=academy).count() + 1
        student_code = f"CS-STU-{academy.id.hex[:4].upper()}-{count:06d}"

        # 3. Create StudentProfile
        profile = StudentProfile.objects.create(
            user=user,
            student_code=student_code,
            display_name=full_name,
            status=StudentStatus.ACTIVE
        )

        # 4. Generate token & send activation email
        try:
            raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
            from emails.services import send_student_activation_email
            send_student_activation_email(user=user, academy=academy, raw_token=raw_token)
        except Exception:
            pass

        return profile

    @staticmethod
    def update_status(student_profile: StudentProfile, new_status: str) -> StudentProfile:
        student_profile.status = new_status
        student_profile.save(update_fields=['status'])

        # Deactivate user login access if inactive or suspended
        if new_status in [StudentStatus.INACTIVE, StudentStatus.SUSPENDED, StudentStatus.ARCHIVED]:
            student_profile.user.is_active = False
            student_profile.user.save(update_fields=['is_active'])
        elif new_status == StudentStatus.ACTIVE:
            student_profile.user.is_active = True
            student_profile.user.save(update_fields=['is_active'])

        return student_profile
