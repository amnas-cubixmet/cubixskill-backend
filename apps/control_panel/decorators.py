from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from users_roles.models import SystemRoleCode


def super_admin_required(view_func):
    """
    Decorator for control panel views ensuring the user is logged in and possesses Super Admin permissions.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
        
        is_super_admin = (
            getattr(request.user, 'role_code', '') in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] or
            getattr(request.user, 'is_superuser', False)
        )
        
        if not is_super_admin:
            from django.shortcuts import render
            return render(request, 'control_panel/403.html', status=403)
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view
