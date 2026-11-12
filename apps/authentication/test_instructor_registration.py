from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from rest_framework.test import APITestCase

from academy.models import Academy
from emails.models import EmailJob
from users_roles.models import SystemRoleCode, User

from .models import InstructorProfile


class InstructorRegistrationTests(APITestCase):
    endpoint = '/api/v1/auth/instructor/register/'

    def setUp(self):
        cache.clear()
        self.payload = {
            'full_name': 'Anu Teacher',
            'email': 'Teacher@example.com',
            'country_code': '+91',
            'mobile': '9876543210',
            'qualification': 'MSc',
            'teaching_subjects': 'Mathematics',
            'years_experience': 0,
            'bio': 'I teach mathematics to high school students.',
        }

    def register(self, **overrides):
        return self.client.post(self.endpoint, {**self.payload, **overrides}, format='json')

    def test_profile_and_instructor_panel_activation(self):
        response = self.register(role_code='SUPER_ADMIN', is_staff=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['data'], {'status': 'pending_activation'})
        self.assertFalse(response.cookies)
        profile = InstructorProfile.objects.select_related('user__academy').get()
        user = profile.user
        self.assertEqual(user.role_code, SystemRoleCode.ACADEMY_ADMIN)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.phone, '+919876543210')
        self.assertEqual(profile.qualification, 'MSc')
        self.assertEqual(profile.teaching_subjects, 'Mathematics')
        self.assertEqual(profile.years_experience, 0)
        self.assertEqual(profile.bio, self.payload['bio'])
        self.assertEqual(user.email, 'teacher@example.com')
        job = EmailJob.objects.get(template_name='academy_activation')
        self.assertEqual(job.academy_uuid, user.academy_id)
        setup_url = urlparse(job.metadata['action_url'])
        self.assertEqual(setup_url.path, '/setup-password')
        token = parse_qs(setup_url.query)['token'][0]
        password = 'A-new-instructor-password-83'
        setup_endpoint = '/api/v1/auth/password/setup/'
        setup_data = {'token': token, 'new_password': password}
        mismatch = self.client.post(setup_endpoint, {
            **setup_data, 'confirm_password': 'A-mismatched-password',
        }, format='json')
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn('confirm_password', mismatch.data['errors'])
        setup = self.client.post(setup_endpoint, {
            **setup_data, 'confirm_password': password,
        }, format='json')
        self.assertEqual(setup.status_code, 200, setup.data)
        self.assertEqual(setup.data['data']['portal'], 'instructor')
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.password_setup_completed)
        credentials = {'email': user.email, 'password': password, 'academy_uuid': str(user.academy_id)}
        login = self.client.post('/api/v1/auth/instructor/login/', credentials, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        self.assertEqual(login.data['data']['portal'], 'instructor')

    def test_required_fields_and_invalid_email_and_mobile(self):
        missing = self.client.post(self.endpoint, {}, format='json')
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(set(missing.data['errors']), set(self.payload))
        self.assertIn('email', self.register(email='broken-email').data['errors'])
        self.assertIn('mobile', self.register(mobile='1234567').data['errors'])
        self.assertFalse(User.objects.exists())
        self.assertFalse(Academy.objects.exists())

    def test_duplicate_email_and_mobile_create_only_one_account(self):
        self.assertEqual(self.register().status_code, 201)
        repeated = self.register(email='TEACHER@EXAMPLE.COM')
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(set(repeated.data['errors']), {'email', 'mobile'})
        duplicate_phone = self.register(email='second@example.com')
        self.assertEqual(set(duplicate_phone.data['errors']), {'mobile'})
        for model in (InstructorProfile, User, Academy, EmailJob):
            self.assertEqual(model.objects.count(), 1)

    def test_existing_formatted_phone_blocks_registration(self):
        User.objects.create_user(email='existing@example.com', full_name='Existing', phone='+91 (98765) 43210')
        response = self.register()
        self.assertEqual(response.status_code, 400)
        self.assertIn('mobile', response.data['errors'])
        self.assertFalse(InstructorProfile.objects.exists())

    def test_resend_is_scoped_to_pending_instructor_registrations(self):
        self.assertEqual(self.register().status_code, 201)
        User.objects.create_user(email='student@example.com', full_name='Student')
        endpoint = '/api/v1/auth/instructor/setup/resend/'
        for email in ['teacher@example.com', 'student@example.com']:
            self.assertEqual(self.client.post(endpoint, {'email': email}, format='json').status_code, 200)
        self.assertEqual(EmailJob.objects.filter(template_name='academy_activation').count(), 2)
        self.assertFalse(EmailJob.objects.filter(template_name='student_activation').exists())
