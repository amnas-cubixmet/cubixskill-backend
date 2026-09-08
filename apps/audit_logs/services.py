import logging

from academy.models import Academy
from audit_logs.models import AuditLog
from django.db import transaction
from django.utils import timezone
from users_roles.models import User

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Sensitive Keys Redaction Set
# Do not store passwords, tokens, payment secrets, or sensitive credentials.
# Prevents sensitive fields from ever being written into AuditLog JSON payloads.
# --------------------------------------------------------------


SENSITIVE_KEYS = {
    'password', 'password_hash', 'token', 'access_token', 'refresh_token',
    'secret', 'api_key', 'webhook_secret', 'card', 'card_number', 'cvv',
    'pin', 'private_key', 'credentials'
}

class AuditService:

    @classmethod
    def sanitize_data(cls, data):
        """
        Recursively sanitizes dictionary/list contents, redacting any sensitive keys.
        """
        if not data:
            return {}

        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(s_key in k_lower for s_key in SENSITIVE_KEYS):
                    sanitized[k] = {'changed': True} if isinstance(v, dict) else '[REDACTED]'
                else:
                    sanitized[k] = cls.sanitize_data(v)
            return sanitized
        elif isinstance(data, list):
            return [cls.sanitize_data(item) for item in data]

        return data

    @classmethod
    @transaction.atomic
    def log(
        cls,
        action: str,
        category: str,
        actor: User = None,
        academy: Academy = None,
        target=None,
        target_type: str = "",
        target_id: str = "",
        target_display: str = "",
        description: str = "",
        changes: dict = None,
        metadata: dict = None,
        request=None,
        ip_address: str = None,
        user_agent: str = None,
        request_id: str = None
    ) -> AuditLog:
        """
        Central entry point for business apps to emit immutable audit records.
        Sanitizes sensitive payload data, records actor snapshots, and attaches request context.
        """
        actor_type = 'USER' if actor else 'SYSTEM'
        actor_display = actor.full_name if (actor and getattr(actor, 'full_name', None)) else (actor.email if actor else 'SYSTEM')
        actor_role = getattr(actor, 'role_code', '') if actor else ''

        academy = academy or (getattr(actor, 'academy', None) if actor else None)
        academy_display = academy.name if academy else ''

        # Target Reference Resolution
        if target:
            target_type = target_type or target.__class__.__name__.upper()
            target_id = target_id or str(getattr(target, 'id', ''))
            target_display = target_display or str(target)

        # Request Context Extraction
        if request and hasattr(request, 'audit_context'):
            request_id = request_id or request.audit_context.request_id
            ip_address = ip_address or request.audit_context.ip_address
            user_agent = user_agent or request.audit_context.user_agent

        # Redact Sensitive Keys
        clean_changes = cls.sanitize_data(changes or {})
        clean_metadata = cls.sanitize_data(metadata or {})

        log_entry = AuditLog.objects.create(
            actor=actor,
            actor_type=actor_type,
            actor_display=actor_display,
            actor_role=actor_role,
            academy=academy,
            academy_display=academy_display,
            action=action,
            category=category,
            target_type=target_type,
            target_id=str(target_id),
            target_display=target_display,
            description=description,
            changes=clean_changes,
            metadata=clean_metadata,
            request_id=request_id or '',
            ip_address=ip_address,
            user_agent=(user_agent or '')[:500],
            occurred_at=timezone.now()
        )

        return log_entry
