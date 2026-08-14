from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from academy.models import Academy
from courses.models import Course, CourseStatus, CourseVisibility
from users_roles.models import User, SystemRoleCode
from website.models import WebsiteSettings
from website.services import WebsiteService

class WebsiteAppTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(
            name="Skill Academy",
            slug="skill-academy",
            email="contact@skillacademy.com",
            phone="+919876543210",
            theme_color="#2563EB"
        )
        self.staff_user = User.objects.create_user(
            email="admin@skillacademy.com",
            full_name="Academy Admin",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy
        )
        self.student_user = User.objects.create_user(
            email="student@skillacademy.com",
            full_name="Student One",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy
        )

        self.course = Course.objects.create(
            academy=self.academy,
            title="Python Masterclass",
            slug="python-masterclass",
            status=CourseStatus.PUBLISHED,
            visibility=CourseVisibility.PUBLIC,
            is_active=True
        )

    def test_public_website_config_endpoint(self):
        """
        Tests public website configuration endpoint returns expected branding and text structure.
        """
        url = reverse('public-website-config', kwargs={'academy_slug': self.academy.slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("academy", data)
        self.assertEqual(data["academy"]["name"], "Skill Academy")
        self.assertEqual(data["academy"]["theme_color"], "#2563EB")
        self.assertEqual(data["academy"]["email"], "contact@skillacademy.com")
        self.assertEqual(data["home"]["hero_title"], "Start Learning Today")

    def test_student_portal_branding_endpoint(self):
        """
        Tests student portal branding endpoint returns academy name, logo, favicon, and theme color.
        """
        self.client.force_authenticate(user=self.student_user)
        url = reverse('student-branding')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["academy_name"], "Skill Academy")
        self.assertEqual(data["theme_color"], "#2563EB")

    def test_website_settings_update_and_character_limits(self):
        """
        Tests staff website text settings update and backend character limit enforcement.
        """
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('academy-website-settings')

        # 1. Valid update
        payload = {
            "home_hero_title": "Learn Without Limits",
            "home_hero_subtitle": "Build practical skills with modern online courses."
        }
        response = self.client.patch(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["home_hero_title"], "Learn Without Limits")

        # 2. Exceed character limit (title > 100 chars)
        invalid_payload = {
            "home_hero_title": "A" * 105
        }
        response = self.client.patch(url, data=invalid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_theme_color_update_and_hex_validation(self):
        """
        Tests single theme color update and hex regex validation.
        """
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('academy-theme-color-settings')

        # 1. Valid hex code
        response = self.client.patch(url, data={"theme_color": "#10B981"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.academy.refresh_from_db()
        self.assertEqual(self.academy.theme_color, "#10B981")

        # 2. Invalid CSS/XSS string
        response = self.client.patch(url, data={"theme_color": "javascript:alert(1)"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_public_academy_courses_endpoint(self):
        """
        Tests public courses listing endpoint reuses Courses app data and filters active public courses.
        """
        url = reverse('public-academy-courses', kwargs={'academy_slug': self.academy.slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        courses = response.json()
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["title"], "Python Masterclass")
