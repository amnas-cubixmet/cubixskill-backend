from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from academy.models import Academy, AcademyStatus
from users_roles.models import User
from authentication.models import AuthToken, TokenType

class StudentRegistrationAuthTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.active_academy = Academy.objects.create(
            name="Test Active Academy",
            slug="test-active-academy",
            email="admin@activeacademy.com",
            status=AcademyStatus.ACTIVE,
            is_active=True
        )
        self.inactive_academy = Academy.objects.create(
            name="Test Inactive Academy",
            slug="test-inactive-academy",
            email="admin@inactiveacademy.com",
            status=AcademyStatus.INACTIVE,
            is_active=False
        )

    def test_student_registration_valid_academy_id(self):
        payload = {
            "academy_uuid": str(self.active_academy.id),
            "full_name": "Test Student",
            "email": "student_test@example.com",
            "phone": "9876543210"
        }
        response = self.client.post('/api/v1/auth/register/student/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get('success'))
        self.assertEqual(response.data.get('status'), 'EMAIL_VERIFICATION_PENDING')
        self.assertIn('st**********@example.com', response.data.get('email_masked'))

        # Check user record
        user = User.objects.filter(email='student_test@example.com').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.password_setup_completed)

    def test_student_registration_invalid_academy_id(self):
        payload = {
            "academy_uuid": "00000000-0000-0000-0000-000000000000",
            "full_name": "Test Student",
            "email": "invalid_acad@example.com"
        }
        response = self.client.post('/api/v1/auth/register/student/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data.get('success'))
        self.assertEqual(response.data.get('code'), 'ACADEMY_NOT_FOUND')

    def test_student_registration_inactive_academy(self):
        payload = {
            "academy_uuid": str(self.inactive_academy.id),
            "full_name": "Test Student",
            "email": "inactive_acad@example.com"
        }
        response = self.client.post('/api/v1/auth/register/student/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get('success'))
        self.assertEqual(response.data.get('code'), 'ACADEMY_INACTIVE')

    def test_resend_verification_email_actual_email(self):
        # First register student
        payload = {
            "academy_uuid": str(self.active_academy.id),
            "full_name": "Resend Student",
            "email": "resend_student@example.com"
        }
        self.client.post('/api/v1/auth/register/student/', data=payload, format='json')
        user = User.objects.get(email="resend_student@example.com")
        initial_tokens_count = AuthToken.objects.filter(user=user, token_type=TokenType.EMAIL_VERIFICATION).count()

        # Resend using actual email
        resend_payload = {
            "academy_uuid": str(self.active_academy.id),
            "email": "resend_student@example.com"
        }
        response = self.client.post('/api/v1/auth/email/verification/resend/', data=resend_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("verification email has been sent", response.data.get('message'))

        # Confirm new token was created and old token revoked
        active_tokens = AuthToken.objects.filter(user=user, token_type=TokenType.EMAIL_VERIFICATION, revoked_at__isnull=True)
        self.assertEqual(active_tokens.count(), 1)

    def test_resend_verification_email_masked_string_rejected_safely(self):
        resend_payload = {
            "academy_uuid": str(self.active_academy.id),
            "email": "re**********@example.com"
        }
        response = self.client.post('/api/v1/auth/email/verification/resend/', data=resend_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("verification email has been sent", response.data.get('message'))


class CookieJWTAuthTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(
            name="Auth Test Academy",
            slug="auth-test-academy",
            email="admin@authtest.com",
            status=AcademyStatus.ACTIVE,
            is_active=True
        )
        self.student_user = User.objects.create_user(
            email="cookie_student@example.com",
            full_name="Cookie Student",
            password="securepassword123",
            role_code="STUDENT",
            academy=self.academy,
            is_email_verified=True,
            password_setup_completed=True,
            is_active=True
        )
        self.instructor_user = User.objects.create_user(
            email="cookie_instructor@example.com",
            full_name="Cookie Instructor",
            password="securepassword123",
            role_code="ACADEMY_ADMIN",
            academy=self.academy,
            is_email_verified=True,
            password_setup_completed=True,
            is_active=True
        )

    def test_student_login_sets_student_cookies(self):
        response = self.client.post('/api/v1/auth/student/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('student_access_token', response.cookies)
        self.assertIn('student_refresh_token', response.cookies)
        self.assertTrue(response.cookies['student_access_token']['httponly'])
        self.assertTrue(response.cookies['student_refresh_token']['httponly'])

    def test_instructor_login_sets_instructor_cookies(self):
        response = self.client.post('/api/v1/auth/instructor/login/', data={
            "email": "cookie_instructor@example.com",
            "password": "securepassword123"
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('instructor_access_token', response.cookies)
        self.assertIn('instructor_refresh_token', response.cookies)
        self.assertTrue(response.cookies['instructor_access_token']['httponly'])
        self.assertTrue(response.cookies['instructor_refresh_token']['httponly'])

    def test_student_cannot_login_to_instructor_portal(self):
        response = self.client.post('/api/v1/auth/instructor/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_instructor_cannot_login_to_student_portal(self):
        response = self.client.post('/api/v1/auth/student/login/', data={
            "email": "cookie_instructor@example.com",
            "password": "securepassword123"
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_concurrent_sessions_and_independent_logout(self):
        # 1. Login student
        student_res = self.client.post('/api/v1/auth/student/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')
        student_access = student_res.cookies['student_access_token'].value
        student_refresh = student_res.cookies['student_refresh_token'].value

        # 2. Login instructor
        instructor_res = self.client.post('/api/v1/auth/instructor/login/', data={
            "email": "cookie_instructor@example.com",
            "password": "securepassword123"
        }, format='json')
        instructor_access = instructor_res.cookies['instructor_access_token'].value
        instructor_refresh = instructor_res.cookies['instructor_refresh_token'].value

        # Set both cookies on client
        self.client.cookies['student_access_token'] = student_access
        self.client.cookies['student_refresh_token'] = student_refresh
        self.client.cookies['instructor_access_token'] = instructor_access
        self.client.cookies['instructor_refresh_token'] = instructor_refresh

        # Student /me/ returns student user
        res_stud_me = self.client.get('/api/v1/auth/student/me/')
        self.assertEqual(res_stud_me.status_code, status.HTTP_200_OK)
        self.assertEqual(res_stud_me.data['data']['user']['email'], "cookie_student@example.com")

        # Instructor /me/ returns instructor user
        res_inst_me = self.client.get('/api/v1/auth/instructor/me/')
        self.assertEqual(res_inst_me.status_code, status.HTTP_200_OK)
        self.assertEqual(res_inst_me.data['data']['user']['email'], "cookie_instructor@example.com")

        # Logout student
        logout_stud = self.client.post('/api/v1/auth/student/logout/')
        self.assertEqual(logout_stud.status_code, status.HTTP_200_OK)
        self.assertEqual(logout_stud.cookies['student_access_token'].value, '')
        self.client.cookies.pop('student_access_token', None)

        # Instructor tab remains valid!
        res_inst_still_ok = self.client.get('/api/v1/auth/instructor/me/')
        self.assertEqual(res_inst_still_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(res_inst_still_ok.data['data']['user']['email'], "cookie_instructor@example.com")


