from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from users_roles.models import SystemRoleCode

def super_admin_required(view_func):
    """
    Decorator for control panel views ensuring the user is logged in and possesses Super Admin permissions.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/control/login/?next={request.path}')
        
        is_super_admin = (
            getattr(request.user, 'role_code', '') in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] or
            getattr(request.user, 'is_superuser', False)
        )
        
        if not is_super_admin:
            messages.error(request, "Access denied. Super Admin privileges required.")
            return redirect('control_panel:login')
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view
