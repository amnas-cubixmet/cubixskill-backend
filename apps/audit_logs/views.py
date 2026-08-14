from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from audit_logs.models import AuditLog
from audit_logs.selectors import AuditLogSelector
from audit_logs.serializers import AuditLogSerializer

# --------------------------------------------------------------
# 1. Academy Audit Logs ViewSet
# Read-only REST endpoints for inspecting tenant-scoped AuditLogs.
# Academy-scoped audit data must respect tenant isolation.
# AuditLog is append-only and should never be silently edited or deleted.
# --------------------------------------------------------------


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy and not getattr(self.request.user, 'is_staff', False):
            return AuditLog.objects.none()

        if getattr(self.request.user, 'is_staff', False) and not academy:
            return AuditLogSelector.get_platform_audit_logs(
                action=self.request.query_params.get('action'),
                category=self.request.query_params.get('category')
            )

        return AuditLogSelector.get_academy_audit_logs(
            academy=academy,
            action=self.request.query_params.get('action'),
            category=self.request.query_params.get('category'),
            target_type=self.request.query_params.get('target_type'),
            date_from=self.request.query_params.get('date_from'),
            date_to=self.request.query_params.get('date_to')
        )

# --------------------------------------------------------------
# 2. Super Admin Platform Audit Logs ViewSet
# Read-only REST endpoints for platform-wide audit log inspection.
# Platform-level audit events may exist outside a specific Academy where supported.
# --------------------------------------------------------------


class AdminAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return AuditLogSelector.get_platform_audit_logs(
            action=self.request.query_params.get('action'),
            category=self.request.query_params.get('category'),
            date_from=self.request.query_params.get('date_from'),
            date_to=self.request.query_params.get('date_to')
        )
