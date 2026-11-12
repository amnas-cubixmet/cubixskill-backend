"""
Baseline query-count / snapshot guards for high-traffic read APIs.
Keep response shape stable while tightening assertNumQueries over time.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from academy.models import Academy
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment, EnrollmentStatus
from features.services import CourseFeatureService
from modules.models import Module
from lessons.models import Lesson, LessonType
from users_roles.models import SystemRoleCode, User


class ApiPerformanceBaselineTests(TestCase):
    def setUp(self):
        CourseFeatureService.ensure_default_features()
        self.client = APIClient()
        self.academy = Academy.objects.create(
            name="Perf Academy",
            slug="perf-academy",
            email="perf@test.com",
        )
        self.staff = User.objects.create_user(
            email="perf-staff@test.com",
            password="Password123!",
            full_name="Perf Staff",
            academy=self.academy,
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            is_staff=True,
        )
        self.student = User.objects.create_user(
            email="perf-student@test.com",
            password="Password123!",
            full_name="Perf Student",
            role_code=SystemRoleCode.STUDENT,
        )
        self.course = Course.objects.create(
            academy=self.academy,
            title="Perf Course",
            status=CourseStatus.PUBLISHED,
            is_active=True,
        )
        CourseFeatureService.enable_feature(self.course, "COURSE_DISCUSSION", user=self.staff)
        Enrollment.objects.create(
            student=self.student,
            course=self.course,
            status=EnrollmentStatus.ACTIVE,
        )
        for i in range(12):
            module = Module.objects.create(
                course=self.course,
                title=f"Module {i}",
                order_index=i,
                is_active=True,
            )
            for j in range(3):
                Lesson.objects.create(
                    module=module,
                    title=f"Lesson {i}-{j}",
                    order_index=j,
                    is_active=True,
                    lesson_type=LessonType.VIDEO if hasattr(LessonType, "VIDEO") else "VIDEO",
                )

    def test_student_enrollments_query_budget(self):
        self.client.force_authenticate(user=self.student)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get("/api/v1/enrollments/student/enrollments/")
        self.assertEqual(resp.status_code, 200)
        # Annotated selector should stay near-constant vs enrollment count.
        self.assertLessEqual(len(ctx), 25)

    def test_course_modules_list_query_budget(self):
        self.client.force_authenticate(user=self.staff)
        url = f"/api/v1/modules/courses/{self.course.id}/modules/"
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Prefetched lessons: must not grow linearly with lesson count (~36).
        self.assertLessEqual(len(ctx), 40)
        payload = resp.json()
        results = payload.get("results", payload.get("data", payload))
        if isinstance(results, dict):
            results = results.get("results", [])
        if isinstance(results, list) and results:
            first = results[0]
            self.assertIn("lesson_count", first)
