from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed


class CookieJWTAuthentication(JWTAuthentication):
    """
    Custom SimpleJWT Authentication class that reads the access token
    from the HttpOnly 'access_token' cookie first, falling back to the standard
    Authorization header if the cookie is not set.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get("access_token")

        if raw_token is None:
            # Fallback to default Authorization header (Bearer token)
            return super().authenticate(request)

        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except (InvalidToken, AuthenticationFailed):
            # If cookie token is invalid/expired, return None or fallback to header authentication
            header_auth = super().authenticate(request)
            if header_auth is not None:
                return header_auth
            raise
