from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import authenticate
from django.utils import timezone
from users_roles.models import User, SystemRoleCode
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
            setup_url = f"http://localhost:5173/setup-password?token={raw_token}"

            try:
                EmailService.send_transactional(
                    recipient=user.email,
                    template_code="ACADEMY_ACCOUNT_SETUP",
                    subject="Activate Your CubixSkill Academy Account",
                    context={
                        "user_name": user.full_name,
                        "action_url": setup_url,
                        "body": f"Hello {user.full_name},\n\nWelcome to CubixSkill! Your Academy '{academy.name}' has been created. Please complete your account setup and set your password by clicking the link below:\n\n{setup_url}\n\nThis link is secure and single-use."
                    },
                    user=user,
                    academy=academy
                )
            except Exception:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject="Activate Your CubixSkill Academy Account",
                    message=f"Hello {user.full_name},\n\nWelcome to CubixSkill! Your Academy '{academy.name}' has been created. Please complete your account setup and set your password by clicking the link below:\n\n{setup_url}\n\nThis link is secure and single-use.",
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com'),
                    recipient_list=[user.email],
                    fail_silently=True
                )

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

        user = authenticate(username=data['email'], password=data['password'])
        if not user or not user.is_active:
            raise CubixSkillAPIException("Invalid credentials or deactivated account.", code="INVALID_CREDENTIALS")

        if not user.is_email_verified or not user.password_setup_completed:
            raise CubixSkillAPIException("Account setup or email verification pending.", code="ACCOUNT_SETUP_PENDING")

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
        user = User.objects.filter(email=email).first()
        if user and (not user.is_email_verified or not user.password_setup_completed):
            if user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
                raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)
                setup_url = f"http://localhost:5173/setup-password?token={raw_token}"
                try:
                    EmailService.send_transactional(
                        recipient=user.email,
                        template_code="ACADEMY_ACCOUNT_SETUP",
                        subject="Activate Your CubixSkill Academy Account",
                        context={
                            "user_name": user.full_name,
                            "action_url": setup_url,
                            "body": f"Hello {user.full_name},\n\nPlease complete your account setup and set your password by clicking the link below:\n\n{setup_url}"
                        },
                        user=user,
                        academy=user.academy
                    )
                except Exception:
                    from django.core.mail import send_mail
                    from django.conf import settings
                    send_mail(
                        subject="Activate Your CubixSkill Academy Account",
                        message=f"Hello {user.full_name},\n\nPlease complete your account setup and set your password by clicking the link below:\n\n{setup_url}",
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com'),
                        recipient_list=[user.email],
                        fail_silently=True
                    )
            else:
                raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                academy_slug = user.academy.slug if user.academy else "app"
                verify_url = f"https://{academy_slug}.cubixskill.com/verify-email?token={raw_token}"
                send_email_task.delay(
                    subject="Verify Your CubixSkill Email",
                    recipient=user.email,
                    message_body=f"Click to verify: {verify_url}"
                )
        return api_response(message="If account exists and is unverified, an activation email has been sent.")


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
        user.save()

        return api_response(message="Password setup complete. You can now login.")

class ForgotPasswordView(APIView):
    """
    Triggers password reset flow.
    Sends reset link if account exists without revealing account existence.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email=email, is_active=True).first()
        if user:
            raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_RESET)
            academy_slug = user.academy.slug if user.academy else "app"
            reset_url = f"https://{academy_slug}.cubixskill.com/reset-password?token={raw_token}"
            try:
                send_email_task.delay(
                    subject="Reset Your CubixSkill Password",
                    recipient=user.email,
                    message_body=f"Click to reset password: {reset_url}"
                )
            except Exception:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject="Reset Your CubixSkill Password",
                    message=f"Click to reset password: {reset_url}",
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com'),
                    recipient_list=[user.email],
                    fail_silently=True
                )

        # Use a generic response to prevent account enumeration.
        return api_response(message="If an account with that email exists, a password reset link has been sent.")


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = AuthTokenService.validate_and_consume(
            raw_token=data['token'],
            expected_type=TokenType.PASSWORD_RESET
        )
        if not user:
            raise CubixSkillAPIException("Invalid or expired reset token.", code="TOKEN_INVALID")

        user.set_password(data['new_password'])
        user.save()

        return api_response(message="Password reset successfully. You can now login with your new password.")

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AuthenticatedPasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        if not user.check_password(data['current_password']):
            raise CubixSkillAPIException("Incorrect current password.", code="INVALID_CURRENT_PASSWORD")

        user.set_password(data['new_password'])
        user.save()

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
                token.blacklist()
            except TokenError:
                pass
        return api_response(message="Successfully logged out.")

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return api_response({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role_code,
            "academy_id": str(user.academy.id) if user.academy else None,
            "is_email_verified": user.is_email_verified
        })
