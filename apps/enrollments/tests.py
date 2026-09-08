from datetime import timedelta

from academy.models import Academy
from core.utils import CubixSkillAPIException
from courses.models import Course
from django.test import TestCase
from django.utils import timezone
from enrollments.models import (
    AccessType,
    EnrollmentEvent,
    EnrollmentEventType,
    EnrollmentStatus,
)
from enrollments.services import EnrollmentAccessService, EnrollmentService
from enrollments.tasks import expire_enrollments_task
from lessons.models import Lesson, LessonType
from modules.models import Module
from rest_framework.test import APIClient
from users_roles.models import SystemRoleCode, User


class EnrollmentsAppTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create Academies
        from decimal import Decimal

        from credits.models import CreditAccount
        self.academy_a = Academy.objects.create(name="Academy A", slug="academy-a", email="info@academya.com")
        self.academy_b = Academy.objects.create(name="Academy B", slug="academy-b", email="info@academyb.com")
        CreditAccount.objects.create(academy=self.academy_a, balance=Decimal('1000.00'))

        # Create Users
        self.admin_a = User.objects.create_user(
            email="admin@academya.com",
            password="Password123!",
            full_name="Academy Admin A",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy_a
        )
        self.student_a = User.objects.create_user(
            email="student@academya.com",
            password="Password123!",
            full_name="Student A",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy_a
        )
        self.student_b = User.objects.create_user(
            email="student@academyb.com",
            password="Password123!",
            full_name="Student B",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy_b
        )

        # Create Course, Module, Lessons
        self.course_a = Course.objects.create(academy=self.academy_a, title="Python Masterclass", price=99.00)
        self.module_a = Module.objects.create(course=self.course_a, title="Module 1")
        self.lesson_demo = Lesson.objects.create(
            module=self.module_a,
            title="Demo Lesson",
            lesson_type=LessonType.VIDEO,
            is_demo=True
        )
        self.lesson_premium = Lesson.objects.create(
            module=self.module_a,
            title="Premium Lesson",
            lesson_type=LessonType.VIDEO,
            is_demo=False
        )

    def test_grant_full_and_demo_access(self):
        """Test creating Full and Demo enrollments."""
        full_enrollment = EnrollmentService.grant_full_access(
            student=self.student_a,
            course=self.course_a,
            is_lifetime=True,
            created_by=self.admin_a
        )
        self.assertEqual(full_enrollment.access_type, AccessType.FULL)
        self.assertEqual(full_enrollment.status, EnrollmentStatus.ACTIVE)
        self.assertTrue(full_enrollment.is_lifetime)
        self.assertTrue(full_enrollment.is_currently_valid())

    def test_academy_boundary_enforcement(self):
        """Verify Student from Academy B cannot be enrolled in Academy A Course."""
        with self.assertRaises(CubixSkillAPIException) as cm:
            EnrollmentService.enroll_student(
                student=self.student_b,
                course=self.course_a,
                access_type=AccessType.FULL
            )
        self.assertEqual(cm.exception.code, "CROSS_ACADEMY_ENROLLMENT_FORBIDDEN")

    def test_access_resolver_course_and_lesson(self):
        """Test central EnrollmentAccessService for Full vs Demo access."""
        # Demo access
        EnrollmentService.grant_demo_access(student=self.student_a, course=self.course_a, duration_days=5)

        can_access_c, _, _ = EnrollmentAccessService.can_access_course(self.student_a, self.course_a)
        self.assertTrue(can_access_c)

        # Demo lesson access allowed
        can_access_demo_l, _, _ = EnrollmentAccessService.can_access_lesson(self.student_a, self.lesson_demo)
        self.assertTrue(can_access_demo_l)

        # Non-demo lesson access denied for DEMO enrollment
        can_access_prem_l, reason, _ = EnrollmentAccessService.can_access_lesson(self.student_a, self.lesson_premium)
        self.assertFalse(can_access_prem_l)
        self.assertEqual(reason, "DEMO_RESTRICTED")

    def test_upgrade_demo_to_full(self):
        """Test upgrading DEMO enrollment to FULL access and audit history creation."""
        enrollment = EnrollmentService.grant_demo_access(student=self.student_a, course=self.course_a, duration_days=3)
        self.assertEqual(enrollment.access_type, AccessType.DEMO)

        upgraded = EnrollmentService.upgrade_demo_to_full(enrollment, is_lifetime=True, performed_by=self.admin_a)
        self.assertEqual(upgraded.access_type, AccessType.FULL)
        self.assertTrue(upgraded.is_lifetime)

        # Premium lesson should now be accessible
        can_access_prem, _, _ = EnrollmentAccessService.can_access_lesson(self.student_a, self.lesson_premium)
        self.assertTrue(can_access_prem)

        # Verify audit event
        events = EnrollmentEvent.objects.filter(enrollment=upgraded, event_type=EnrollmentEventType.UPGRADED_TO_FULL)
        self.assertTrue(events.exists())

    def test_extension_and_expiration_task(self):
        """Test access extension and Celery background auto-expiration task."""
        now = timezone.now()
        past_expiry = now - timedelta(days=1)
        enrollment = EnrollmentService.enroll_student(
            student=self.student_a,
            course=self.course_a,
            access_type=AccessType.FULL,
            is_lifetime=False,
            access_starts_at=now - timedelta(days=10),
            access_expires_at=past_expiry
        )
        self.assertFalse(enrollment.is_currently_valid())

        # Run background task
        expire_enrollments_task()
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, EnrollmentStatus.EXPIRED)

        # Extend access
        extended = EnrollmentService.extend_access(enrollment, additional_days=30, reason="Granted extra month", performed_by=self.admin_a)
        self.assertEqual(extended.status, EnrollmentStatus.ACTIVE)
        self.assertTrue(extended.is_currently_valid())

    def test_suspension_resumption_revocation(self):
        """Test lifecycle actions: suspend, resume, revoke."""
        enrollment = EnrollmentService.grant_full_access(student=self.student_a, course=self.course_a)

        # Suspend
        EnrollmentService.suspend_enrollment(enrollment, reason="Payment default", performed_by=self.admin_a)
        self.assertEqual(enrollment.status, EnrollmentStatus.SUSPENDED)
        can_access, _, _ = EnrollmentAccessService.can_access_course(self.student_a, self.course_a)
        self.assertFalse(can_access)

        # Resume
        EnrollmentService.resume_enrollment(enrollment, reason="Payment cleared", performed_by=self.admin_a)
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)
        can_access_res, _, _ = EnrollmentAccessService.can_access_course(self.student_a, self.course_a)
        self.assertTrue(can_access_res)

        # Revoke
        EnrollmentService.revoke_enrollment(enrollment, reason="Permanent cancellation", performed_by=self.admin_a)
        self.assertEqual(enrollment.status, EnrollmentStatus.REVOKED)

    def test_bulk_enrollment(self):
        """Test bulk enrollment service."""
        student_a2 = User.objects.create_user(
            email="student2@academya.com",
            password="Password123!",
            full_name="Student A2",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy_a
        )

        results = EnrollmentService.bulk_enroll(
            students=[self.student_a, student_a2],
            course=self.course_a,
            access_type=AccessType.FULL,
            created_by=self.admin_a
        )
        self.assertEqual(results['successful_count'], 2)
        self.assertEqual(results['failed_count'], 0)

    def test_student_and_admin_api_permissions(self):
        """Test REST API access permissions for Student vs Admin."""
        enrollment = EnrollmentService.grant_full_access(student=self.student_a, course=self.course_a)

        # Student GET own enrollments
        self.client.force_authenticate(user=self.student_a)
        res = self.client.get('/api/v1/enrollments/student/enrollments/')
        self.assertEqual(res.status_code, 200)

        # Student CANNOT suspend enrollment
        res_suspend = self.client.post(f'/api/v1/enrollments/enrollments/{enrollment.id}/suspend/', {'reason': 'illegal'})
        self.assertEqual(res_suspend.status_code, 403)

        # Admin CAN suspend enrollment
        self.client.force_authenticate(user=self.admin_a)
        res_admin_suspend = self.client.post(f'/api/v1/enrollments/enrollments/{enrollment.id}/suspend/', {'reason': 'Admin action'})
        self.assertEqual(res_admin_suspend.status_code, 200)
        self.assertEqual(res_admin_suspend.data['status'], EnrollmentStatus.SUSPENDED)

    def test_student_lesson_detail_with_resources(self):
        """Test student lesson detail endpoint returns attached resources."""
        from lessons.models import LessonResource
        from storage.models import MediaFile

        enrollment = EnrollmentService.grant_full_access(student=self.student_a, course=self.course_a)

        mf = MediaFile.objects.create(
            academy_uuid=self.academy_a.id,
            original_filename="cheatsheet.pdf",
            storage_key="documents/cheatsheet.pdf",
            relative_path="documents/cheatsheet.pdf",
            mime_type="application/pdf",
            size_bytes=1024500,
        )
        resource = LessonResource.objects.create(
            lesson=self.lesson_demo,
            media_file=mf,
            title="Lesson Cheatsheet",
            resource_type="pdf",
            allow_download=True,
        )

        self.client.force_authenticate(user=self.student_a)
        url = f'/api/v1/enrollments/student/enrollments/academies/{self.academy_a.id}/courses/{self.course_a.id}/lessons/{self.lesson_demo.id}/'
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertIn('resources', res.data)
        self.assertIn('resources', res.data['lesson'])
        self.assertEqual(len(res.data['resources']), 1)

        res_item = res.data['resources'][0]
        self.assertEqual(res_item['id'], str(resource.id))
        self.assertEqual(res_item['title'], "Lesson Cheatsheet")
        self.assertTrue(res_item['allow_download'])
        self.assertTrue("cheatsheet.pdf" in res_item['url'] or "cheatsheet.pdf" in res_item['file_name'])
