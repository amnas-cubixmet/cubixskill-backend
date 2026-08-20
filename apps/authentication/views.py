from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import authenticate
from django.utils import timezone
from users_roles.models import User, SystemRoleCode, get_user_permissions
from academy.models import Academy

from students.models import StudentProfile
from authentication.models import AuthTokenService, TokenType
from django.db import transaction
from academy.models import Academy, AcademyStatus
from authentication.serializers import (
    RegisterStudentSerializer, RegisterAcademySerializer, LoginSerializer, TokenVerifySerializer,
    PasswordSetupSerializer, ForgotPasswordSerializer, PasswordResetSerializer,
    AuthenticatedPasswordChangeSerializer
)
from emails.services import (
    send_academy_activation_email,
    send_password_reset_email,
    send_password_changed_email,
    send_verification_email
)

class RegisterAcademyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterAcademySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(email=data['email']).exists():
            raise CubixSkillAPIException("An account with this email address already exists.", code="USER_EXISTS")

        with transaction.atomic():
            academy = Academy.objects.create(
                name=data['academy_name'],
                email=data['email'],
                phone=data.get('phone', ''),
                status=AcademyStatus.ACTIVE,
                is_active=True,
                feature_config={}
            )


            user = User.objects.create_user(
                email=data['email'],
                full_name=data['full_name'],
                phone=data.get('phone', ''),
                role_code=SystemRoleCode.ACADEMY_ADMIN,
                academy=academy,
                is_email_verified=False,
                password_setup_completed=False,
                is_active=True
            )

            raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)
            send_academy_activation_email(user=user, academy=academy, raw_token=raw_token)

            return api_response(
                data={
                    "email": user.email,
                    "academy_name": academy.name,
                    "academy_slug": academy.slug
                },
                message="Registration submitted successfully. Please check your email to activate your Academy account.",
                status_code=status.HTTP_201_CREATED
            )

from authentication.tasks import send_email_task
from notifications.services import EmailService
from core.utils import CubixSkillAPIException, api_response

#--------------------------------------------------------------
# Registration & Login Views
#--------------------------------------------------------------

class RegisterStudentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            academy = Academy.objects.get(slug=data['academy_slug'])
        except Academy.DoesNotExist:
            raise CubixSkillAPIException("Academy not found.", code="ACADEMY_NOT_FOUND")

        if User.objects.filter(email=data['email'], academy=academy).exists():
            raise CubixSkillAPIException("User with this email already exists in this academy.", code="USER_EXISTS")

        user = User.objects.create_user(
            email=data['email'],
            full_name=data['name'],
            phone=data['phone'],
            role_code=SystemRoleCode.STUDENT,
            academy=academy,
            is_email_verified=False,
            password_setup_completed=False
        )

        student_code = f"STD-{academy.id.hex[:4].upper()}-{User.objects.filter(academy=academy, role_code=SystemRoleCode.STUDENT).count()}"
        StudentProfile.objects.create(
            user=user,
            student_code=student_code,
            display_name=data['name']
        )

        raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
        verify_url = f"https://{academy.slug}.cubixskill.com/verify-email?token={raw_token}"

        # Central Transactional Email Dispatch via EmailService
        EmailService.send_transactional(
            recipient=user.email,
            template_code="EMAIL_VERIFICATION",
            subject="Verify Your CubixSkill Email",
            context={
                "user_name": user.full_name,
                "action_url": verify_url,
                "body": f"Hello {user.full_name},\n\nPlease verify your email by clicking the link below:\n{verify_url}"
            },
            idempotency_key=f"email-verification:{user.id.hex}:{raw_token[:10]}",
            user=user,
            academy=academy
        )

        return api_response(
            data={"email": user.email, "academy": academy.slug},
            message="Student registration successful. Email verification link sent.",
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
#  Login Views
#--------------------------------------------------------------

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        password = data['password']

        user = User.objects.filter(email__iexact=email).first()
        if not user or not user.check_password(password):
            raise CubixSkillAPIException(
                "Invalid email or password. Please try again.",
                code="INVALID_CREDENTIALS",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            raise CubixSkillAPIException(
                "Your account is disabled. Please contact your academy administrator.",
                code="ACCOUNT_DISABLED",
                status_code=status.HTTP_403_FORBIDDEN
            )

        if user.academy and not user.academy.is_active:
            raise CubixSkillAPIException(
                "Your academy account is inactive. Please contact support.",
                code="ACADEMY_INACTIVE",
                status_code=status.HTTP_403_FORBIDDEN
            )

        if not user.is_email_verified or not user.password_setup_completed:
            raise CubixSkillAPIException(
                "Account setup or email verification is pending. Please check your activation email.",
                code="ACCOUNT_SETUP_PENDING",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        refresh = RefreshToken.for_user(user)
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        return api_response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None
            }
        })

#--------------------------------------------------------------
# Email Verification & Resend
#--------------------------------------------------------------

class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TokenVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = AuthTokenService.validate_and_consume(
            raw_token=serializer.validated_data['token'],
            expected_type=TokenType.EMAIL_VERIFICATION
        )
        if not user:
            raise CubixSkillAPIException("Invalid or expired verification token.", code="TOKEN_INVALID")

        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])

        # Generate setup token for password setup flow
        setup_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)

        return api_response({
            "message": "Email verified successfully.",
            "password_setup_token": setup_token
        })

class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            raise CubixSkillAPIException("Email is required.", code="EMAIL_REQUIRED")

        # Rate limiting: max 3 requests per 5 minutes per email/IP
        from django.core.cache import cache
        ip = request.META.get('REMOTE_ADDR', '')
        cache_key = f"resend_email_rate:{email}:{ip}"
        resend_count = cache.get(cache_key, 0)
        if resend_count >= 3:
            # Safe generic message to avoid leaking rate limit state or account existence
            return api_response(message="If account exists and is unverified, an activation email has been sent.")

        cache.set(cache_key, resend_count + 1, timeout=300)

        email = email.strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user and (not user.is_email_verified or not user.password_setup_completed):
            if user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
                raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)
                send_academy_activation_email(user=user, academy=user.academy, raw_token=raw_token)
            else:
                raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                send_verification_email(user=user, raw_token=raw_token)

        return api_response(message="An activation email has been sent if an unverified account exists for that address.")


class TokenValidateView(APIView):
    """
    Validates single-use tokens (peek without consuming).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            raise CubixSkillAPIException("Token is required.", code="TOKEN_REQUIRED")

        user = AuthTokenService.validate_token_peek(
            raw_token=token,
            expected_types=[TokenType.PASSWORD_SETUP, TokenType.PASSWORD_RESET, TokenType.EMAIL_VERIFICATION]
        )
        if not user:
            raise CubixSkillAPIException("Token is invalid, expired, or already used.", code="TOKEN_INVALID")

        return api_response({
            "valid": True,
            "email": user.email,
            "user_name": user.full_name
        }, message="Token is valid.")

# --------------------------------------------------------------
# Password Flows: Setup, Forgot, Reset, Change
# --------------------------------------------------------------


class SetupPasswordView(APIView):
    """
    Sets initial password for a user.
    Password setup is allowed only after email verification or via single-use setup token.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Tokens are single-use and must not be stored in plaintext.
        user = AuthTokenService.validate_and_consume(
            raw_token=data['token'],
            expected_type=TokenType.PASSWORD_SETUP
        )
        if not user:
            user = AuthTokenService.validate_and_consume(
                raw_token=data['token'],
                expected_type=TokenType.PASSWORD_RESET
            )
        if not user:
            user = AuthTokenService.validate_and_consume(
                raw_token=data['token'],
                expected_type=TokenType.EMAIL_VERIFICATION
            )
        if not user:
            raise CubixSkillAPIException("Invalid or expired password setup token.", code="TOKEN_INVALID")


        user.set_password(data['new_password'])
        user.is_email_verified = True
        user.password_setup_completed = True
        user.last_login = timezone.now()
        user.save()

        if not user.check_password(data['new_password']):
            raise CubixSkillAPIException("Password setup failed. Please try again.", code="PASSWORD_UPDATE_FAILED")

        send_password_changed_email(user=user)

        refresh = RefreshToken.for_user(user)

        return api_response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None
            }
        }, message="Password setup completed successfully.")

class ForgotPasswordView(APIView):
    """
    Triggers password reset flow.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            raise CubixSkillAPIException(
                {"email": ["This email address is not registered."]},
                code="EMAIL_NOT_FOUND",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_RESET)
        send_password_reset_email(user=user, raw_token=raw_token)

        return api_response(message="Password reset instructions sent to your email address.")


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        auth_token, user, error_msg, error_code = AuthTokenService.validate_reset_token(data['token'])
        if not auth_token or not user:
            raise CubixSkillAPIException(error_msg, code=error_code)

        with transaction.atomic():
            user.set_password(data['new_password'])
            user.save()

            if not user.check_password(data['new_password']):
                raise CubixSkillAPIException("Password update failed. Please try again.", code="PASSWORD_UPDATE_FAILED")

            AuthTokenService.mark_token_used(auth_token)
            AuthTokenService.revoke_existing_tokens(user, TokenType.PASSWORD_RESET)

            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

        refresh = RefreshToken.for_user(user)

        return api_response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None
            }
        }, message="Password reset successfully.")

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AuthenticatedPasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        if not user.check_password(data['current_password']):
            raise CubixSkillAPIException(
                {"current_password": ["Incorrect current password."]},
                code="INVALID_CURRENT_PASSWORD",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(data['new_password'])
        user.save()

        if not user.check_password(data['new_password']):
            raise CubixSkillAPIException("Password update failed. Please try again.", code="PASSWORD_UPDATE_FAILED")

        send_password_changed_email(user=user)

        return api_response(message="Password changed successfully.")

#--------------------------------------------------------------
# JWT & Session Management
#--------------------------------------------------------------

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                if hasattr(token, 'blacklist'):
                    token.blacklist()
            except Exception:
                pass
        return api_response(message="Successfully logged out.")

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        academy = user.academy

        academy_data = None
        features = {}
        demo_status = None

        if academy:
            academy_data = {
                "id": str(academy.id),
                "name": academy.name,
                "slug": academy.slug,
                "email": academy.email,
                "phone": academy.phone,
                "theme": academy.theme,
                "theme_color": academy.theme_color,
                "status": academy.status,
                "is_active": academy.is_active,
                "logo_url": academy.logo.file.url if academy.logo and hasattr(academy.logo, 'file') and academy.logo.file else None,
                "favicon_url": academy.favicon.file.url if academy.favicon and hasattr(academy.favicon, 'file') and academy.favicon.file else None,
            }
            features = academy.get_enabled_features()
            demo_status = academy.get_demo_status()

        permissions = get_user_permissions(user)

        user_data = {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role_code,
            "assigned_role_name": user.assigned_role.name if user.assigned_role else None,
            "academy_id": str(academy.id) if academy else None,
            "is_email_verified": user.is_email_verified,
            "is_active": user.is_active,
            "password_setup_completed": user.password_setup_completed,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }

        return api_response({
            "user": user_data,
            "academy": academy_data,
            "permissions": permissions,
            "features": features,
            "demo_status": demo_status
        })

