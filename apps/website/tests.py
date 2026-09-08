from academy.models import Academy
from courses.models import Course, CourseStatus, CourseVisibility
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users_roles.models import SystemRoleCode, User


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
        self.assertIn("home", data)

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

    def test_website_settings_update_and_draft_publish_flow(self):
        """
        Tests single theme draft update and publish operation.
        """
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('academy-website-settings')

        # 1. Update draft theme
        payload = {
            "primary_color": "#8B5CF6",
            "home_hero_title": "Learn Without Limits",
            "home_hero_subtitle": "Build practical skills with modern online courses."
        }
        response = self.client.patch(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.json()
        self.assertEqual(res_data["draft_config"]["primary_color"], "#8B5CF6")
        self.assertEqual(res_data["draft_config"]["home_hero_title"], "Learn Without Limits")
        self.assertTrue(res_data["has_unpublished_changes"])

        # 2. Publish draft theme
        publish_url = reverse('academy-website-publish')
        pub_response = self.client.post(publish_url)
        self.assertEqual(pub_response.status_code, status.HTTP_200_OK)
        pub_data = pub_response.json()
        self.assertEqual(pub_data["published_config"]["primary_color"], "#8B5CF6")
        self.assertFalse(pub_data["has_unpublished_changes"])

        # Verify Academy model theme_color was updated
        self.academy.refresh_from_db()
        self.assertEqual(self.academy.theme_color, "#8B5CF6")

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
