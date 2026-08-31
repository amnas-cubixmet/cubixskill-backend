import urllib.parse
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from users_roles.models import User

@database_sync_to_async
def get_user_from_token(token_key):
    try:
        access_token = AccessToken(token_key)
        user_id = access_token.get('user_id')
        if user_id:
            return User.objects.get(id=user_id, is_active=True)
    except Exception:
        pass
    return AnonymousUser()
#--------------------------------------------------------------
# 1. Token Auth Middleware
#--------------------------------------------------------------

class TokenAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get('user') and scope['user'].is_authenticated:
            return await self.inner(scope, receive, send)

        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = urllib.parse.parse_qs(query_string)
        token = None

        if 'token' in query_params:
            token = query_params['token'][0]
        else:
            # Check headers for Authorization header or Cookie header
            headers = dict(scope.get('headers', []))
            if b'authorization' in headers:
                auth_header = headers[b'authorization'].decode('utf-8')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
            elif b'cookie' in headers:
                cookie_str = headers[b'cookie'].decode('utf-8')
                cookies = urllib.parse.parse_qs(cookie_str.replace('; ', '&'))
                # Priority: instructor_access_token -> student_access_token -> access_token
                for cookie_name in ['instructor_access_token', 'student_access_token', 'access_token']:
                    if cookie_name in cookies and cookies[cookie_name]:
                        token = cookies[cookie_name][0]
                        break

        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)
