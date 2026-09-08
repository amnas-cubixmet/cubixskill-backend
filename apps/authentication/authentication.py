from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from users_roles.models import SystemRoleCode


class StudentCookieJWTAuthentication(JWTAuthentication):
    """
    Reads HttpOnly 'student_access_token' cookie FIRST.
    Falls back to Authorization header for backward compatibility.
    Enforces 'student' portal claim and STUDENT user role.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get("student_access_token")
        if not raw_token:
            header_auth = super().authenticate(request)
            if header_auth:
                user, token = header_auth
                if user and user.role_code == SystemRoleCode.STUDENT:
                    return user, token
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            # Portal claim check if present
            portal = validated_token.get("portal")
            if portal and portal != "student":
                return None

            user = self.get_user(validated_token)
            if not user or user.role_code != SystemRoleCode.STUDENT:
                return None

            return user, validated_token
        except (InvalidToken, AuthenticationFailed):
            header_auth = super().authenticate(request)
            if header_auth:
                user, token = header_auth
                if user and user.role_code == SystemRoleCode.STUDENT:
                    return user, token
            return None


class InstructorCookieJWTAuthentication(JWTAuthentication):
    """
    Reads HttpOnly 'instructor_access_token' cookie FIRST.
    Falls back to Authorization header for backward compatibility.
    Enforces 'instructor' portal claim and ACADEMY_ADMIN / ACADEMY_STAFF / SUPER_ADMIN role.
    """

    ALLOWED_ROLES = {
        SystemRoleCode.ACADEMY_ADMIN,
        SystemRoleCode.ACADEMY_STAFF,
        SystemRoleCode.SUPER_ADMIN,
        SystemRoleCode.SUPER_ADMIN_STAFF,
    }

    def authenticate(self, request):
        raw_token = request.COOKIES.get("instructor_access_token")
        if not raw_token:
            header_auth = super().authenticate(request)
            if header_auth:
                user, token = header_auth
                if user and user.role_code in self.ALLOWED_ROLES:
                    return user, token
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            # Portal claim check if present
            portal = validated_token.get("portal")
            if portal and portal != "instructor":
                return None

            user = self.get_user(validated_token)
            if not user or user.role_code not in self.ALLOWED_ROLES:
                return None

            return user, validated_token
        except (InvalidToken, AuthenticationFailed):
            header_auth = super().authenticate(request)
            if header_auth:
                user, token = header_auth
                if user and user.role_code in self.ALLOWED_ROLES:
                    return user, token
            return None


class CookieJWTAuthentication(JWTAuthentication):
    """
    Portal-aware Cookie Authentication class.
    Determines whether to authenticate via Student or Instructor cookie based on endpoint path/header.
    Does NOT fall back between student_access_token and instructor_access_token for private APIs.
    """

    def authenticate(self, request):
        path = request.path_info.lower()
        header_portal = request.headers.get("X-Portal", "").lower()

        # Check explicit portal context
        is_student = (
            header_portal == "student" or
            "/student/" in path or
            "/auth/student/" in path or
            "/enrollments/student/" in path or
            "/certificates/student/" in path or
            "/live-classes/student/" in path
        )

        is_instructor = (
            header_portal == "instructor" or
            "/instructor/" in path or
            "/auth/instructor/" in path or
            "/academy/" in path or
            "/control-panel/" in path
        )

        if is_student:
            return StudentCookieJWTAuthentication().authenticate(request)
        elif is_instructor:
            return InstructorCookieJWTAuthentication().authenticate(request)

        # Fallback for general endpoints: try instructor cookie first then student cookie based on token presence
        if "instructor_access_token" in request.COOKIES and "student_access_token" not in request.COOKIES:
            return InstructorCookieJWTAuthentication().authenticate(request)
        elif "student_access_token" in request.COOKIES and "instructor_access_token" not in request.COOKIES:
            return StudentCookieJWTAuthentication().authenticate(request)
        elif "instructor_access_token" in request.COOKIES:
            return InstructorCookieJWTAuthentication().authenticate(request)
        elif "student_access_token" in request.COOKIES:
            return StudentCookieJWTAuthentication().authenticate(request)

        # Legacy fallback if access_token exists
        raw_token = request.COOKIES.get("access_token")
        if raw_token:
            try:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token
            except Exception:
                pass

        # Header fallback (e.g. Bearer token)
        return super().authenticate(request)

