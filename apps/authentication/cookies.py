from django.conf import settings


def get_cookie_names(portal='student'):
    if portal == 'instructor':
        return 'instructor_access_token', 'instructor_refresh_token'
    elif portal == 'student':
        return 'student_access_token', 'student_refresh_token'
    return 'access_token', 'refresh_token'


def set_auth_cookies(response, access_token, refresh_token, portal='student'):
    """
    Sets portal-specific access_token and refresh_token HttpOnly cookies on the HTTP response.
    Also clears legacy shared cookies if present.
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

    access_key, refresh_key = get_cookie_names(portal)

    if access_token:
        response.set_cookie(
            key=access_key,
            value=str(access_token),
            max_age=access_lifetime,
            **cookie_kwargs,
        )

    if refresh_token:
        response.set_cookie(
            key=refresh_key,
            value=str(refresh_token),
            max_age=refresh_lifetime,
            **cookie_kwargs,
        )

    # Clear legacy un-suffixed cookies during migration if present
    delete_kwargs = {'path': cookie_kwargs['path']}
    if domain:
        delete_kwargs['domain'] = domain
    response.delete_cookie("access_token", **delete_kwargs)
    response.delete_cookie("refresh_token", **delete_kwargs)

    return response


def delete_auth_cookies(response, portal='student'):
    """
    Removes access_token and refresh_token cookies for the given portal (or all) from the response.
    """
    path = getattr(settings, 'AUTH_COOKIE_PATH', '/')
    domain = getattr(settings, 'AUTH_COOKIE_DOMAIN', None)

    delete_kwargs = {'path': path}
    if domain:
        delete_kwargs['domain'] = domain

    if portal == 'all':
        response.delete_cookie("student_access_token", **delete_kwargs)
        response.delete_cookie("student_refresh_token", **delete_kwargs)
        response.delete_cookie("instructor_access_token", **delete_kwargs)
        response.delete_cookie("instructor_refresh_token", **delete_kwargs)
    else:
        access_key, refresh_key = get_cookie_names(portal)
        response.delete_cookie(access_key, **delete_kwargs)
        response.delete_cookie(refresh_key, **delete_kwargs)

    response.delete_cookie("access_token", **delete_kwargs)
    response.delete_cookie("refresh_token", **delete_kwargs)

    return response

