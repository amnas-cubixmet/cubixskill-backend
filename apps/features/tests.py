from django.test import TestCase
from rest_framework.test import APIClient
from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from enrollments.services import EnrollmentService
from features.models import Feature, CourseFeature, FeatureScope
from features.services import (
    CourseFeatureService,
    StudentFeatureService,
    AcademyFeatureService,
)

class FeaturesSystemTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create Academy
        self.academy = Academy.objects.create(name="Cubix Academy")
        self.other_academy = Academy.objects.create(name="Other Academy")

        # Create Users
        self.super_admin = User.objects.create_user(
            email="superadmin@cubix.com",
            password="Password123!",
            role_code="SUPER_ADMIN",
            academy=self.academy,
            is_superuser=True
        )
        self.student = User.objects.create_user(
            email="student@cubix.com",
            password="Password123!",
            role_code="STUDENT",
            academy=self.academy
        )

        # Create Courses
        self.course_python = Course.objects.create(
            academy=self.academy,
            title="Python Masterclass"
        )
        self.course_java = Course.objects.create(
            academy=self.academy,
            title="Java Enterprise"
        )
        self.course_uiux = Course.objects.create(
            academy=self.academy,
            title="UI/UX Design"
        )

        # Create Global Features
        self.feature_chat = Feature.objects.create(
            name="Chat",
            code="chat",
            category="COMMUNICATION",
            scope=FeatureScope.COURSE
        )
        self.feature_reports = Feature.objects.create(
            name="Reports",
            code="course_reports",
            category="ANALYTICS",
            scope=FeatureScope.COURSE
        )
        self.feature_certs = Feature.objects.create(
            name="Certificates",
            code="certificates",
            category="COMPLETION",
            scope=FeatureScope.COURSE
        )

        # Enroll Student in Python and UI/UX (Not Java)
        EnrollmentService.grant_full_access(self.student, self.course_python)
        EnrollmentService.grant_full_access(self.student, self.course_uiux)

    def test_course_feature_enable_and_disable(self):
        """
        Verify CourseFeature toggle functionality and cache invalidation.
        """
        # Initially disabled
        self.assertFalse(CourseFeatureService.has_feature(self.course_python, "chat"))

        # Enable Chat for Python
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        self.assertTrue(CourseFeatureService.has_feature(self.course_python, "chat"))

        # Disable Chat for Python (historical row retained)
        cf = CourseFeatureService.disable_feature(self.course_python, "chat", user=self.super_admin)
        self.assertFalse(CourseFeatureService.has_feature(self.course_python, "chat"))
        self.assertIsNotNone(cf.disabled_at)
        self.assertTrue(CourseFeature.objects.filter(course=self.course_python, feature=self.feature_chat).exists())

    def test_feature_isolation_across_courses(self):
        """
        Critical Rule Test: Enabling Chat on Python MUST NOT enable Chat on Java or UI/UX.
        """
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        CourseFeatureService.enable_feature(self.course_java, "course_reports", user=self.super_admin)

        # Course Python has Chat = ON, Reports = OFF
        self.assertTrue(CourseFeatureService.has_feature(self.course_python, "chat"))
        self.assertFalse(CourseFeatureService.has_feature(self.course_python, "course_reports"))

        # Course Java has Chat = OFF, Reports = ON
        self.assertFalse(CourseFeatureService.has_feature(self.course_java, "chat"))
        self.assertTrue(CourseFeatureService.has_feature(self.course_java, "course_reports"))

        # Course UI/UX has Chat = OFF, Reports = OFF
        self.assertFalse(CourseFeatureService.has_feature(self.course_uiux, "chat"))
        self.assertFalse(CourseFeatureService.has_feature(self.course_uiux, "course_reports"))

    def test_global_feature_deactivation_override(self):
        """
        If Feature.is_active = False, it must return False even if CourseFeature.is_enabled = True.
        """
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        self.assertTrue(CourseFeatureService.has_feature(self.course_python, "chat"))

        # Globally deactivate feature
        self.feature_chat.is_active = False
        self.feature_chat.save()

        # Invalidate cache to test DB resolution
        CourseFeatureService.invalidate_course_cache(self.course_python.id, "chat")
        self.assertFalse(CourseFeatureService.has_feature(self.course_python, "chat"))

    def test_student_feature_resolution(self):
        """
        Verify Student feature access depends on Enrollment + Course Feature status.
        """
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        CourseFeatureService.enable_feature(self.course_java, "chat", user=self.super_admin)

        # Enrolled in Python with Chat ON -> Access True
        self.assertTrue(StudentFeatureService.has_course_feature(self.student, self.course_python, "chat"))

        # Enrolled in UI/UX with Chat OFF -> Access False
        self.assertFalse(StudentFeatureService.has_course_feature(self.student, self.course_uiux, "chat"))

        # NOT enrolled in Java (even though Java Chat is ON) -> Access False
        self.assertFalse(StudentFeatureService.has_course_feature(self.student, self.course_java, "chat"))

    def test_student_available_features_global_nav(self):
        """
        Verify student navigation receives features from courses they are enrolled in.
        """
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        CourseFeatureService.enable_feature(self.course_java, "certificates", user=self.super_admin)

        available = StudentFeatureService.get_available_features(self.student)
        self.assertIn("chat", available)
        # Certificates is only on Java (student not enrolled), so it shouldn't appear
        self.assertNotIn("certificates", available)

    def test_derived_academy_feature_summary(self):
        """
        Verify Academy feature list is derived from enabled features across its courses.
        """
        CourseFeatureService.enable_feature(self.course_python, "chat", user=self.super_admin)
        CourseFeatureService.enable_feature(self.course_java, "chat", user=self.super_admin)
        CourseFeatureService.enable_feature(self.course_java, "course_reports", user=self.super_admin)

        summary = AcademyFeatureService.get_academy_used_features(self.academy)
        summary_map = {item['code']: item['enabled_course_count'] for item in summary}

        # Chat enabled in 2 courses (Python & Java)
        self.assertEqual(summary_map.get('chat'), 2)
        # Reports enabled in 1 course (Java)
        self.assertEqual(summary_map.get('course_reports'), 1)
        # Certificates enabled in 0 courses -> not present in summary
        self.assertNotIn('certificates', summary_map)

    def test_course_feature_rest_apis(self):
        """
        Integration test for REST endpoints.
        """
        self.client.force_authenticate(user=self.super_admin)

        # 1. Enable Chat via API
        enable_url = f"/api/v1/courses/{self.course_python.id}/features/chat/enable/"
        response = self.client.post(enable_url, {"config": {"students_can_post": True}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_enabled'])

        # 2. List Course features
        list_url = f"/api/v1/courses/{self.course_python.id}/features/"
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, 200)

        # 3. Student features API
        self.client.force_authenticate(user=self.student)
        student_url = f"/api/v1/student/courses/{self.course_python.id}/features/"
        response = self.client.get(student_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['features']['chat'])

        # 4. Academy feature summary API
        self.client.force_authenticate(user=self.super_admin)
        academy_url = f"/api/v1/academy/features/?academy_id={self.academy.id}"
        response = self.client.get(academy_url)
        self.assertEqual(response.status_code, 200)
        codes = [item['code'] for item in response.data['features']]
        self.assertIn('chat', codes)
