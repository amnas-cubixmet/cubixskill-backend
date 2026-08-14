#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.contrib import admin
from users_roles.models import User, Role, Permission, RolePermission, UserPermissionOverride

#--------------------------------------------------------------
# Admin Configurations
#--------------------------------------------------------------

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'role_code', 'academy', 'is_active', 'is_email_verified', 'created_at')
    list_filter = ('role_code', 'is_active', 'is_email_verified', 'academy')
    search_fields = ('email', 'full_name', 'phone')
    ordering = ('-created_at',)

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'scope', 'is_system_role', 'is_active')
    list_filter = ('scope', 'is_system_role', 'is_active')
    search_fields = ('name', 'code')

@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'module')
    list_filter = ('module',)
    search_fields = ('code', 'name')

@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('role', 'permission')
    list_filter = ('role',)

@admin.register(UserPermissionOverride)
class UserPermissionOverrideAdmin(admin.ModelAdmin):
    list_display = ('user', 'permission', 'is_granted')
    list_filter = ('is_granted',)
    search_fields = ('user__email', 'permission__code')
