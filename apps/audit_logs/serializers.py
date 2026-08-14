from rest_framework import serializers
from audit_logs.models import AuditLog

# --------------------------------------------------------------
# Audit Log Serializers
# Provides structured read-only representations of append-only AuditLog records.
# Exposes actor, target, action, timestamp, and trusted request context.
# Do not store or output passwords, tokens, payment secrets, or sensitive credentials.
# --------------------------------------------------------------


class AuditLogSerializer(serializers.ModelSerializer):
    academy_id = serializers.UUIDField(source='academy.id', read_only=True)
    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'action',
            'category',
            'actor',
            'actor_type',
            'academy_id',
            'academy_display',
            'target',
            'description',
            'changes',
            'metadata',
            'request_id',
            'ip_address',
            'user_agent',
            'occurred_at',
        ]
        read_only_fields = fields

    def get_actor(self, obj) -> dict:
        return {
            'id': str(obj.actor_id) if obj.actor_id else None,
            'name': obj.actor_display or 'SYSTEM',
            'role': obj.actor_role or ('SYSTEM' if obj.actor_type == 'SYSTEM' else ''),
            'type': obj.actor_type
        }

    def get_target(self, obj) -> dict:
        return {
            'type': obj.target_type,
            'id': obj.target_id,
            'display': obj.target_display
        }
