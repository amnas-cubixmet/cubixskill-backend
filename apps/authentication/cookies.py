from django.conf import settings


def set_auth_cookies(response, access_token, refresh_token):
    """
    Sets access_token and refresh_token HttpOnly cookies on the HTTP response.
    """
    access_lifetime = int(settings.SIMPLE_JWT.get('ACCESS_TOKEN_LIFETIME').total_seconds())
    refresh_lifetime = int(settings.SIMPLE_JWT.get('REFRESH_TOKEN_LIFETIME').total_seconds())

    cookie_kwargs = {
        'httponly': True,
        'secure': getattr(settings, 'AUTH_COOKIE_SECURE', not settings.DEBUG),
        'samesite': getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax'),
        'path': getattr(settings, 'AUTH_COOKIE_PATH', '/'),
    }

    domain = getattr(settings, 'AUTH_COOKIE_DOMAIN', None)
    if domain:
        cookie_kwargs['domain'] = domain

    if access_token:
        response.set_cookie(
            key="access_token",
            value=str(access_token),
            max_age=access_lifetime,
            **cookie_kwargs,
        )

    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=str(refresh_token),
            max_age=refresh_lifetime,
            **cookie_kwargs,
        )

    return response


def delete_auth_cookies(response):
    """
    Removes access_token and refresh_token cookies from the response.
    """
    path = getattr(settings, 'AUTH_COOKIE_PATH', '/')
    domain = getattr(settings, 'AUTH_COOKIE_DOMAIN', None)

    delete_kwargs = {'path': path}
    if domain:
        delete_kwargs['domain'] = domain

    response.delete_cookie("access_token", **delete_kwargs)
    response.delete_cookie("refresh_token", **delete_kwargs)
    return response
