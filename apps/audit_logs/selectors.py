from django.db.models import QuerySet
from academy.models import Academy
from audit_logs.models import AuditLog

# --------------------------------------------------------------
# Audit Log Selectors
# Optimized read queries for Academy-scoped and Platform-wide audit logs.
# Academy-scoped audit data must respect tenant isolation.
# Platform-level audit events may exist outside a specific Academy where supported.
# --------------------------------------------------------------


class AuditLogSelector:

    @classmethod
    def get_academy_audit_logs(
        cls,
        academy: Academy,
        action: str = None,
        category: str = None,
        actor=None,
        target_type: str = None,
        date_from=None,
        date_to=None
    ) -> QuerySet[AuditLog]:
        """
        Retrieves tenant-scoped audit logs for an Academy.
        """
        queryset = AuditLog.objects.filter(academy=academy).select_related('actor', 'academy')

        if action:
            queryset = queryset.filter(action=action)
        if category:
            queryset = queryset.filter(category=category)
        if actor:
            queryset = queryset.filter(actor=actor)
        if target_type:
            queryset = queryset.filter(target_type=target_type)
        if date_from:
            queryset = queryset.filter(occurred_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(occurred_at__lte=date_to)

        return queryset.order_by('-occurred_at')

    @classmethod
    def get_platform_audit_logs(
        cls,
        action: str = None,
        category: str = None,
        academy: Academy = None,
        date_from=None,
        date_to=None
    ) -> QuerySet[AuditLog]:
        """
        Retrieves platform-wide audit logs for Super Admin inspection.
        """
        queryset = AuditLog.objects.select_related('actor', 'academy').all()

        if academy:
            queryset = queryset.filter(academy=academy)
        if action:
            queryset = queryset.filter(action=action)
        if category:
            queryset = queryset.filter(category=category)
        if date_from:
            queryset = queryset.filter(occurred_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(occurred_at__lte=date_to)

        return queryset.order_by('-occurred_at')
