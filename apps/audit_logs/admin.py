from django.contrib import admin
from audit_logs.models import AuditLog

# --------------------------------------------------------------
# Audit Log Admin Registration
# AuditLog is append-only and should never be silently edited or deleted.
# Audit logs record important administrative and security actions.
# Prohibits add, change, and delete operations to enforce immutability.
# --------------------------------------------------------------


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'category', 'actor_display', 'actor_role', 'target_type', 'target_display', 'academy_display', 'occurred_at']
    list_filter = ['action', 'category', 'actor_type']
    search_fields = ['action', 'actor_display', 'target_display', 'description', 'request_id', 'ip_address']
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
