from academy.models import Academy
from audit_logs.models import AuditAction, AuditCategory
from audit_logs.selectors import AuditLogSelector
from audit_logs.services import AuditService
from courses.models import Course, CourseStatus
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users_roles.models import SystemRoleCode, User

# --------------------------------------------------------------
# Audit Log Unit & Integration Tests
# Validates append-only creation, sensitive payload redaction,
# system actor logging, tenant isolation, and read-only REST endpoints.
# --------------------------------------------------------------


class AuditLogsTestCase(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Audit Academy", slug="audit-academy")
        self.user = User.objects.create_user(
            email="admin@auditacademy.com",
            full_name="Audit Admin",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy
        )
        self.course = Course.objects.create(
            academy=self.academy,
            title="Audit Course",
            slug="audit-course",
            status=CourseStatus.DRAFT
        )

    def test_audit_service_log_creates_record(self):
        """
        Tests that AuditService.log creates immutable audit record with actor snapshot and target reference.
        """
        log_entry = AuditService.log(
            action=AuditAction.COURSE_PUBLISHED,
            category=AuditCategory.COURSE,
            actor=self.user,
            academy=self.academy,
            target=self.course,
            description="Course published.",
            changes={'status': {'before': 'DRAFT', 'after': 'PUBLISHED'}}
        )

        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.action, AuditAction.COURSE_PUBLISHED)
        self.assertEqual(log_entry.category, AuditCategory.COURSE)
        self.assertEqual(log_entry.actor, self.user)
        self.assertEqual(log_entry.actor_display, "Audit Admin")
        self.assertEqual(log_entry.target_type, "COURSE")
        self.assertEqual(log_entry.changes['status']['after'], 'PUBLISHED')

    def test_sensitive_data_redaction(self):
        """
        Tests that sensitive keys like password and token are redacted automatically.
        """
        log_entry = AuditService.log(
            action=AuditAction.USER_CREATED,
            category=AuditCategory.AUTHENTICATION,
            actor=self.user,
            academy=self.academy,
            description="User created.",
            changes={
                'email': 'newuser@example.com',
                'password': 'super_secret_password_123',
                'api_key': 'key_abc_xyz'
            }
        )

        self.assertEqual(log_entry.changes['email'], 'newuser@example.com')
        self.assertEqual(log_entry.changes['password'], '[REDACTED]')
        self.assertEqual(log_entry.changes['api_key'], '[REDACTED]')

    def test_system_actor_log(self):
        """
        Tests that system-generated actions record actor_type='SYSTEM'.
        """
        log_entry = AuditService.log(
            action=AuditAction.ENROLLMENT_SUSPENDED,
            category=AuditCategory.ENROLLMENT,
            actor=None,
            academy=self.academy,
            description="Enrollment expired automatically by system."
        )

        self.assertIsNone(log_entry.actor)
        self.assertEqual(log_entry.actor_type, 'SYSTEM')
        self.assertEqual(log_entry.actor_display, 'SYSTEM')

    def test_tenant_isolation_in_audit_selectors(self):
        """
        Tests that Academy audit selectors enforce tenant isolation.
        """
        other_academy = Academy.objects.create(name="Other Academy", slug="other-academy")
        AuditService.log(
            action=AuditAction.COURSE_PUBLISHED,
            category=AuditCategory.COURSE,
            actor=self.user,
            academy=self.academy
        )
        AuditService.log(
            action=AuditAction.ACADEMY_UPDATED,
            category=AuditCategory.ACADEMY,
            actor=None,
            academy=other_academy
        )

        academy_logs = AuditLogSelector.get_academy_audit_logs(self.academy)
        self.assertEqual(academy_logs.count(), 1)
        self.assertEqual(academy_logs.first().action, AuditAction.COURSE_PUBLISHED)

    def test_audit_logs_rest_endpoints(self):
        """
        Tests read-only REST endpoints for audit log listing.
        """
        self.client.force_authenticate(user=self.user)
        AuditService.log(
            action=AuditAction.COURSE_FEATURE_ENABLED,
            category=AuditCategory.COURSE,
            actor=self.user,
            academy=self.academy,
            target=self.course
        )

        url = reverse('audit-log-list')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()['results']), 1)
        self.assertEqual(res.json()['results'][0]['action'], AuditAction.COURSE_FEATURE_ENABLED)
