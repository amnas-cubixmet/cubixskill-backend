from django.test import SimpleTestCase

from audit_logs.models import AuditAction, AuditLog


class AuditLogChoiceTests(SimpleTestCase):
    def test_support_ticket_actions_are_available(self):
        choices = dict(AuditLog._meta.get_field('action').choices)
        for action in (AuditAction.TICKET_CREATED, AuditAction.TICKET_UPDATED, AuditAction.TICKET_REPLIED):
            with self.subTest(action=action):
                self.assertIn(action, choices)
