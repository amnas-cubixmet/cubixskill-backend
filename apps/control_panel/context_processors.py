from users_roles.models import get_user_permissions, SystemRoleCode

def control_panel_permissions(request):
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'user_perms': set(),
            'is_super_admin_owner': False,
        }

    user = request.user
    is_super_admin_owner = (user.role_code == SystemRoleCode.SUPER_ADMIN or getattr(user, 'is_superuser', False))
    perms_list = get_user_permissions(user)

    return {
        'user_perms': set(perms_list),
        'is_super_admin_owner': is_super_admin_owner,
    }
