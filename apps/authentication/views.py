import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.utils import timezone
from django.db import transaction

from users_roles.models import User, SystemRoleCode, get_user_permissions
from academy.models import Academy, AcademyStatus
from academy.resolver import resolve_academy
from students.models import StudentProfile
from .models import AuthTokenService, TokenType
from .serializers import (
    RegisterStudentSerializer, RegisterAcademySerializer, LoginSerializer, TokenVerifySerializer,
    PasswordSetupSerializer, ForgotPasswordSerializer, PasswordResetSerializer,
    AuthenticatedPasswordChangeSerializer, ResendSetupEmailSerializer, ResendVerificationSerializer
)
from emails.services import (
    send_academy_activation_email,
    send_password_reset_email,
    send_password_changed_email,
    send_verification_email,
    send_student_activation_email,
)
from core.utils import CubixSkillAPIException, api_response
from .cookies import set_auth_cookies, delete_auth_cookies
from .authentication import StudentCookieJWTAuthentication, InstructorCookieJWTAuthentication
from django.conf import settings

logger = logging.getLogger(__name__)

def mask_email(email: str) -> str:
    if not email or '@' not in email:
        return email
    parts = email.split('@')
    name = parts[0]
    domain = parts[1]
    if len(name) <= 2:
        masked_name = name[0] + '*'
    else:
        masked_name = name[:2] + '*' * (len(name) - 2)
    return f"{masked_name}@{domain}"


def create_portal_token(user, portal='student'):
    refresh = RefreshToken.for_user(user)
    refresh['portal'] = portal
    refresh.access_token['portal'] = portal
    return refresh



class RegisterAcademyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterAcademySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(email__iexact=data['email']).exists():
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
                    "academy_slug": academy.slug,
                    "academy_uuid": str(academy.pk)
                },
                message="Registration submitted successfully. Please check your email to activate your Academy account.",
                status_code=status.HTTP_201_CREATED
            )


#--------------------------------------------------------------
# Registration & Login Views
#--------------------------------------------------------------

class RegisterStudentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        academy_identifier = data.get('academy_uuid') or data.get('academy_slug')
        academy = resolve_academy(academy_identifier)

        if not academy:
            return Response(
                {
                    "success": False,
                    "code": "ACADEMY_NOT_FOUND",
                    "message": "Academy not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not academy.is_active or academy.status != AcademyStatus.ACTIVE:
            return Response(
                {
                    "success": False,
                    "code": "ACADEMY_INACTIVE",
                    "message": "This academy is currently unavailable."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = data['email'].strip().lower()
        full_name = data['resolved_name']
        phone = data.get('phone', '')

        user = User.objects.filter(email__iexact=email).first()

        if user:
            # Global user exists
            if user.password_setup_completed and user.is_email_verified:
                profile, created = StudentProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'display_name': full_name,
                        'student_code': f"STD-{academy.id.hex[:4].upper()}-{StudentProfile.objects.count() + 1}"
                    }
                )
                return Response(
                    {
                        "success": True,
                        "status": "ALREADY_ACTIVE",
                        "email_masked": mask_email(email),
                        "message": "An account already exists for this email. You can log in directly with your existing password."
                    },
                    status=status.HTTP_200_OK
                )
            elif not user.is_email_verified:
                raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                send_verification_email(user=user, academy=academy, raw_token=raw_token)
                return Response(
                    {
                        "success": True,
                        "status": "EMAIL_VERIFICATION_PENDING",
                        "email_masked": mask_email(email),
                        "message": "Registration successful. Please verify your email."
                    },
                    status=status.HTTP_200_OK
                )
            else:
                raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)
                send_student_activation_email(user=user, academy=academy, raw_token=raw_token)
                return Response(
                    {
                        "success": True,
                        "status": "PASSWORD_SETUP_PENDING",
                        "email_masked": mask_email(email),
                        "message": "Your student email is verified. Check your email for the password setup link."
                    },
                    status=status.HTTP_200_OK
                )

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                full_name=full_name,
                phone=phone,
                role_code=SystemRoleCode.STUDENT,
                academy=academy,
                is_email_verified=False,
                password_setup_completed=False,
                is_active=True
            )

            student_code = f"STD-{academy.id.hex[:4].upper()}-{StudentProfile.objects.count() + 1}"
            StudentProfile.objects.create(
                user=user,
                student_code=student_code,
                display_name=full_name
            )

            raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
            send_verification_email(user=user, academy=academy, raw_token=raw_token)

        return Response(
            {
                "success": True,
                "status": "EMAIL_VERIFICATION_PENDING",
                "email_masked": mask_email(email),
                "message": "Registration successful. Please verify your email."
            },
            status=status.HTTP_201_CREATED
        )


class ResendVerificationEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        academy_identifier = data.get('academy_uuid') or data.get('academy_slug')
        academy = resolve_academy(academy_identifier)

        generic_response = api_response(message="If an eligible account exists, a verification email has been sent.")

        # Reject masked email attempts safely without throwing 500
        if not email or '*' in email:
            logger.warning(f"Resend verification attempt ignored for invalid or masked email: {email}")
            return generic_response

        # Throttling / Rate-limiting by IP and email
        from django.core.cache import cache
        ip = request.META.get('REMOTE_ADDR', '')
        cache_key = f"resend_verify_rate:{email}:{ip}"
        resend_count = cache.get(cache_key, 0)
        if resend_count >= 5:
            return generic_response

        cache.set(cache_key, resend_count + 1, timeout=300)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and not user.is_email_verified:
            target_academy = academy or user.academy
            # Tenant isolation check
            is_valid_tenant = False
            if target_academy:
                if user.academy and user.academy.pk == target_academy.pk:
                    is_valid_tenant = True
                elif StudentProfile.objects.filter(user=user).exists():
                    is_valid_tenant = True
            else:
                is_valid_tenant = True

            if is_valid_tenant:
                try:
                    AuthTokenService.revoke_existing_tokens(user, TokenType.EMAIL_VERIFICATION)
                    raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                    send_verification_email(user=user, academy=target_academy, raw_token=raw_token)
                except Exception as e:
                    logger.exception(
                        "Student verification email resend failed",
                        extra={
                            "academy_id": str(target_academy.pk) if target_academy else None,
                            "user_id": str(user.pk),
                        }
                    )

        return generic_response


class ResendSetupEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendSetupEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        academy_identifier = data.get('academy_uuid') or data.get('academy_slug')
        academy = resolve_academy(academy_identifier)

        user = User.objects.filter(email__iexact=email).first()
        if user and not user.password_setup_completed:
            target_academy = academy or user.academy
            raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)
            send_student_activation_email(user=user, academy=target_academy, raw_token=raw_token)

        return api_response(message="If an eligible account exists, a password setup email has been sent.")


#--------------------------------------------------------------
# Login Views
#--------------------------------------------------------------

class LoginView(APIView):
    permission_classes = [AllowAny]
    portal = None

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        portal = self.portal or request.data.get('portal') or request.headers.get('X-Portal')
        if not portal:
            path = request.path_info.lower()
            if '/student/' in path:
                portal = 'student'
            elif '/instructor/' in path:
                portal = 'instructor'
            else:
                portal = 'student'

        email = data['email'].strip().lower()
        password = data['password']

        user = User.objects.filter(email__iexact=email).first()

        if user:
            if not user.is_email_verified:
                raise CubixSkillAPIException(
                    "Please verify your email before signing in.",
                    code="EMAIL_VERIFICATION_REQUIRED",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if not user.password_setup_completed:
                raise CubixSkillAPIException(
                    "Please use the password setup link sent to your email.",
                    code="PASSWORD_SETUP_REQUIRED",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

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

        # Enforce portal role restrictions
        if portal == 'student':
            if user.role_code != SystemRoleCode.STUDENT:
                raise CubixSkillAPIException(
                    "This account is not authorized to log into the Student Portal.",
                    code="STUDENT_ROLE_REQUIRED",
                    status_code=status.HTTP_403_FORBIDDEN
                )
        elif portal == 'instructor':
            instructor_roles = {
                SystemRoleCode.ACADEMY_ADMIN,
                SystemRoleCode.ACADEMY_STAFF,
                SystemRoleCode.SUPER_ADMIN,
                SystemRoleCode.SUPER_ADMIN_STAFF,
            }
            if user.role_code not in instructor_roles:
                raise CubixSkillAPIException(
                    "This account is not authorized to log into the Instructor Portal.",
                    code="INSTRUCTOR_ROLE_REQUIRED",
                    status_code=status.HTTP_403_FORBIDDEN
                )

        refresh = create_portal_token(user, portal=portal)
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        resp = api_response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'portal': portal,
            'user': {
                'id': str(user.id),
                'account_number': user.account_number or f"CS-{user.pk:06d}" if isinstance(user.pk, int) else "CS-001001",
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None,
                'academy_uuid': str(user.academy.pk) if user.academy else None
            }
        })
        return set_auth_cookies(resp, str(refresh.access_token), str(refresh), portal=portal)


class StudentLoginView(LoginView):
    portal = 'student'


class InstructorLoginView(LoginView):
    portal = 'instructor'



#--------------------------------------------------------------
# Email Verification & Token Peek
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
            raise CubixSkillAPIException("This verification link has expired or is no longer valid.", code="TOKEN_INVALID", status_code=status.HTTP_400_BAD_REQUEST)

        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])

        setup_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_SETUP)

        return api_response({
            "success": True,
            "status": "PASSWORD_SETUP_PENDING",
            "password_setup_token": setup_token,
            "email_masked": mask_email(user.email),
            "academy_uuid": str(user.academy.pk) if user.academy else None
        }, message="Email verified successfully. You can now create your password.")


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        generic_response = api_response(message="If an eligible account exists, a verification email has been sent.")

        if not email or '*' in email:
            return generic_response

        from django.core.cache import cache
        ip = request.META.get('REMOTE_ADDR', '')
        cache_key = f"resend_email_rate:{email}:{ip}"
        resend_count = cache.get(cache_key, 0)
        if resend_count >= 5:
            return generic_response

        cache.set(cache_key, resend_count + 1, timeout=300)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and not user.is_email_verified:
            try:
                AuthTokenService.revoke_existing_tokens(user, TokenType.EMAIL_VERIFICATION)
                raw_token = AuthTokenService.generate_token(user, TokenType.EMAIL_VERIFICATION)
                send_verification_email(user=user, academy=user.academy, raw_token=raw_token)
            except Exception as e:
                logger.exception(
                    "Verification email resend failed",
                    extra={
                        "academy_id": str(user.academy.pk) if user.academy else None,
                        "user_id": str(user.pk),
                    }
                )

        return generic_response


class TokenValidateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            raise CubixSkillAPIException("Token is required.", code="TOKEN_REQUIRED", status_code=status.HTTP_400_BAD_REQUEST)

        user = AuthTokenService.validate_token_peek(
            raw_token=token,
            expected_types=[TokenType.PASSWORD_SETUP, TokenType.PASSWORD_RESET, TokenType.EMAIL_VERIFICATION]
        )
        if not user:
            raise CubixSkillAPIException("This link is no longer valid, expired, or has already been used.", code="TOKEN_INVALID", status_code=status.HTTP_400_BAD_REQUEST)

        return api_response({
            "valid": True,
            "email": user.email,
            "user_name": user.full_name,
            "email_masked": mask_email(user.email),
            "academy_uuid": str(user.academy.pk) if user.academy else None
        }, message="Token is valid.")


# --------------------------------------------------------------
# Password Flows: Setup, Forgot, Reset, Change
# --------------------------------------------------------------

class SetupPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

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
            raise CubixSkillAPIException("This password setup link is no longer valid or has expired.", code="TOKEN_INVALID", status_code=status.HTTP_400_BAD_REQUEST)

        user.set_password(data['new_password'])
        user.is_email_verified = True
        user.password_setup_completed = True
        user.last_login = timezone.now()
        user.save()

        send_password_changed_email(user=user)

        portal = 'student' if user.role_code == SystemRoleCode.STUDENT else 'instructor'
        refresh = create_portal_token(user, portal=portal)

        resp = api_response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'portal': portal,
            'user': {
                'id': str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None,
                'academy_uuid': str(user.academy.pk) if user.academy else None
            }
        }, message="Password created successfully. Your account is ready.")
        return set_auth_cookies(resp, str(refresh.access_token), str(refresh), portal=portal)


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        logger.info(f"Forgot-password request received for email: {email[:3]}***@***")
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            logger.info(f"No active account found for forgot-password: email={email}")
            raise CubixSkillAPIException(
                {"email": ["No account found with this email address."]},
                code="EMAIL_NOT_FOUND",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        logger.info(f"User lookup completed for forgot-password: user_id={user.pk}")
        raw_token = AuthTokenService.generate_token(user, TokenType.PASSWORD_RESET)
        logger.info("Password reset token generated")
        send_password_reset_email(user=user, raw_token=raw_token)
        logger.info("Password reset email job created and queued")

        return api_response(message="Password reset instructions have been sent to your email.")



class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        auth_token, user, error_msg, error_code = AuthTokenService.validate_reset_token(data['token'])
        if not auth_token or not user:
            raise CubixSkillAPIException("This password reset link has expired or is invalid.", code=error_code or "TOKEN_INVALID", status_code=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user.set_password(data['new_password'])
            user.is_email_verified = True
            user.password_setup_completed = True
            user.save()

            AuthTokenService.mark_token_used(auth_token)
            AuthTokenService.revoke_existing_tokens(user, TokenType.PASSWORD_RESET)

            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

        portal = 'student' if user.role_code == SystemRoleCode.STUDENT else 'instructor'
        refresh = create_portal_token(user, portal=portal)

        resp = api_response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'portal': portal,
            'user': {
                'id': str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role_code,
                'academy_id': str(user.academy.id) if user.academy else None,
                'academy_uuid': str(user.academy.pk) if user.academy else None
            }
        }, message="Password reset successfully.")
        return set_auth_cookies(resp, str(refresh.access_token), str(refresh), portal=portal)


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

        send_password_changed_email(user=user)

        return api_response(message="Password changed successfully.")


#--------------------------------------------------------------
# JWT & Session Management
#--------------------------------------------------------------

class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    portal = None

    def post(self, request):
        portal = self.portal or request.data.get('portal') or request.headers.get('X-Portal')
        if not portal:
            path = request.path_info.lower()
            if '/student/' in path:
                portal = 'student'
            elif '/instructor/' in path:
                portal = 'instructor'
            else:
                portal = 'student'

        cookie_key = f"{portal}_refresh_token"
        raw_refresh = request.COOKIES.get(cookie_key) or request.COOKIES.get("refresh_token") or request.data.get("refresh")
        if not raw_refresh:
            raise CubixSkillAPIException("Refresh token is required.", code="TOKEN_REQUIRED", status_code=status.HTTP_401_UNAUTHORIZED)

        try:
            token = RefreshToken(raw_refresh)
            token_portal = token.get("portal")
            if token_portal and token_portal != portal:
                raise CubixSkillAPIException("Invalid portal refresh token.", code="TOKEN_INVALID", status_code=status.HTTP_401_UNAUTHORIZED)

            token['portal'] = portal
            new_access = token.access_token
            new_access['portal'] = portal
            new_refresh = None

            simple_jwt_settings = getattr(settings, 'SIMPLE_JWT', {})
            rotate_refresh = simple_jwt_settings.get('ROTATE_REFRESH_TOKENS', False)
            blacklist_after_rotation = simple_jwt_settings.get('BLACKLIST_AFTER_ROTATION', False)

            if rotate_refresh:
                if blacklist_after_rotation:
                    try:
                        token.blacklist()
                    except AttributeError:
                        pass
                token.set_jti()
                token.set_exp()
                token.outstand()
                new_refresh = token
            else:
                new_refresh = raw_refresh

            resp = api_response({"detail": "Access token refreshed.", "portal": portal})
            return set_auth_cookies(resp, str(new_access), str(new_refresh), portal=portal)
        except TokenError as e:
            raise CubixSkillAPIException("Invalid or expired refresh token.", code="TOKEN_INVALID", status_code=status.HTTP_401_UNAUTHORIZED)


class StudentCookieTokenRefreshView(CookieTokenRefreshView):
    portal = 'student'


class InstructorCookieTokenRefreshView(CookieTokenRefreshView):
    portal = 'instructor'


class LogoutView(APIView):
    permission_classes = [AllowAny]
    portal = None

    def post(self, request):
        portal = self.portal or request.data.get('portal') or request.headers.get('X-Portal')
        if not portal:
            path = request.path_info.lower()
            if '/student/' in path:
                portal = 'student'
            elif '/instructor/' in path:
                portal = 'instructor'
            else:
                portal = 'student'

        cookie_key = f"{portal}_refresh_token"
        refresh_token = request.COOKIES.get(cookie_key) or request.COOKIES.get('refresh_token') or request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                if hasattr(token, 'blacklist'):
                    token.blacklist()
            except Exception:
                pass
        resp = api_response(message="Successfully logged out.")
        return delete_auth_cookies(resp, portal=portal)


class StudentLogoutView(LogoutView):
    portal = 'student'


class InstructorLogoutView(LogoutView):
    portal = 'instructor'


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
                "uuid": str(academy.pk),
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
            "account_number": user.account_number or f"CS-001001",
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role_code,
            "assigned_role_name": user.assigned_role.name if user.assigned_role else None,
            "academy_id": str(academy.id) if academy else None,
            "academy_uuid": str(academy.pk) if academy else None,
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


class StudentCurrentUserView(CurrentUserView):
    authentication_classes = [StudentCookieJWTAuthentication]


class InstructorCurrentUserView(CurrentUserView):
    authentication_classes = [InstructorCookieJWTAuthentication]

