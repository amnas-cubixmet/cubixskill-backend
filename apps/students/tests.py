import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from academy.models import Academy
from students.models import StudentProfile

User = get_user_model()

class StudentProfileJsonTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy")
        self.user = User.objects.create_user(
            email="student_test@example.com",
            password="Password123!",
            full_name="Original Name",
            phone="+919876543210",
            academy=self.academy
        )
        self.profile, _ = StudentProfile.objects.get_or_create(
            user=self.user,
            defaults={'display_name': "Original Name"}
        )

    def test_student_profile_patch_json_success(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/v1/students/student/profile/',
            {
                'full_name': 'Muhammed Ashraf',
                'phone': '+919999999999'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertEqual(self.user.full_name, 'Muhammed Ashraf')
        self.assertEqual(self.user.phone, '+919999999999')
        self.assertEqual(self.profile.display_name, 'Muhammed Ashraf')

    def test_student_profile_patch_json_invalid_name_fails(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/v1/students/student/profile/',
            {
                'full_name': 'Muhammed123'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
