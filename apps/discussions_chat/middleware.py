import urllib.parse
from http.cookies import SimpleCookie
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from users_roles.models import User, SystemRoleCode


@database_sync_to_async
def get_user_from_portal_token(token_key: str, portal: str):
    try:
        access_token = AccessToken(token_key)

        token_portal = access_token.get("portal")
        if token_portal != portal:
            return AnonymousUser()

        user_id = access_token.get("user_id")
        if not user_id:
            return AnonymousUser()

        user = User.objects.get(id=user_id, is_active=True)

        if portal == "student":
            if user.role_code != SystemRoleCode.STUDENT:
                return AnonymousUser()

        elif portal == "instructor":
            allowed_roles = {
                SystemRoleCode.ACADEMY_ADMIN,
                SystemRoleCode.ACADEMY_STAFF,
                SystemRoleCode.SUPER_ADMIN,
                SystemRoleCode.SUPER_ADMIN_STAFF,
            }
            if user.role_code not in allowed_roles:
                return AnonymousUser()
        else:
            return AnonymousUser()

        return user

    except Exception:
        return AnonymousUser()


class TokenAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = urllib.parse.parse_qs(query_string)

        portal = (query_params.get("portal", [None])[0] or "").strip().lower()

        if portal not in {"student", "instructor"}:
            scope["user"] = AnonymousUser()
            return await self.inner(scope, receive, send)

        cookie_name = "student_access_token" if portal == "student" else "instructor_access_token"

        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8")
        raw_token = None

        if cookie_header:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            morsel = cookie.get(cookie_name)
            if morsel:
                raw_token = morsel.value

        if raw_token:
            scope["user"] = await get_user_from_portal_token(raw_token, portal)
        else:
            scope["user"] = AnonymousUser()

        return await self.inner(scope, receive, send)
