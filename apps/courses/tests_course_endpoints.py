from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from features.models import Feature, CourseFeature
from features.services import CourseFeatureService
from control_panel.models import PricingService


class CourseEndpointsTestCase(TestCase):
    def setUp(self):
        CourseFeatureService.ensure_default_features()
        PricingService.ensure_default_rules()

        self.academy1 = Academy.objects.create(name="Academy One", slug="academy-one")
        self.academy2 = Academy.objects.create(name="Academy Two", slug="academy-two")

        self.user1 = User.objects.create_user(
            email="instructor1@example.com",
            password="Password123!",
            full_name="Instructor One",
            academy=self.academy1,
            role_code="INSTRUCTOR"
        )
        self.user2 = User.objects.create_user(
            email="instructor2@example.com",
            password="Password123!",
            full_name="Instructor Two",
            academy=self.academy2,
            role_code="INSTRUCTOR"
        )

        self.course1 = Course.objects.create(
            academy=self.academy1,
            title="Course One",
            slug="course-one"
        )
        self.course2 = Course.objects.create(
            academy=self.academy2,
            title="Course Two",
            slug="course-two"
        )

        self.client1 = APIClient()
        self.client1.force_authenticate(user=self.user1)

        self.client2 = APIClient()
        self.client2.force_authenticate(user=self.user2)

    def test_get_course_detail_200(self):
        url = f"/api/v1/courses/courses/{self.course1.id}/"
        response = self.client1.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.course1.id))

        # Root URL alias check
        url_root = f"/api/v1/courses/{self.course1.id}/"
        response_root = self.client1.get(url_root)
        self.assertEqual(response_root.status_code, status.HTTP_200_OK)

    def test_get_course_features_200(self):
        url = f"/api/v1/courses/courses/{self.course1.id}/features/"
        response = self.client1.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("features", response.data)
        self.assertIn("total_per_student_credits", response.data)
        self.assertEqual(response.data["total_per_student_credits"], 102)

    def test_cross_academy_access_blocked(self):
        url = f"/api/v1/courses/courses/{self.course2.id}/features/"
        response = self.client1.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        detail_url = f"/api/v1/courses/courses/{self.course2.id}/"
        response_detail = self.client1.get(detail_url)
        self.assertEqual(response_detail.status_code, status.HTTP_404_NOT_FOUND)
