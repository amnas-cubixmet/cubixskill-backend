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
        self.user = User.objects.create_user(
            email="cookie_student@example.com",
            full_name="Cookie Student",
            password="securepassword123",
            academy=self.academy,
            is_email_verified=True,
            password_setup_completed=True,
            is_active=True
        )

    def test_cookie_login_sets_httponly_cookies(self):
        response = self.client.post('/api/v1/auth/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])
        self.assertTrue(response.cookies['refresh_token']['httponly'])

    def test_auth_me_with_cookie(self):
        login_res = self.client.post('/api/v1/auth/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')
        access_cookie = login_res.cookies['access_token'].value

        self.client.cookies['access_token'] = access_cookie
        response = self.client.get('/api/v1/auth/me/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['user']['email'], "cookie_student@example.com")

    def test_cookie_token_refresh(self):
        login_res = self.client.post('/api/v1/auth/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')
        refresh_cookie = login_res.cookies['refresh_token'].value

        self.client.cookies['refresh_token'] = refresh_cookie
        response = self.client.post('/api/v1/auth/token/refresh/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])

    def test_cookie_logout_clears_cookies(self):
        login_res = self.client.post('/api/v1/auth/login/', data={
            "email": "cookie_student@example.com",
            "password": "securepassword123"
        }, format='json')
        self.client.cookies['access_token'] = login_res.cookies['access_token'].value
        self.client.cookies['refresh_token'] = login_res.cookies['refresh_token'].value

        response = self.client.post('/api/v1/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Confirm cookies are deleted (expired or empty)
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')

