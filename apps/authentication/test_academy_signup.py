"""Smoke/regression coverage for public academy registration and activation emails."""
import json
from unittest.mock import patch

from academy.models import Academy
from authentication.models import AuthToken, TokenType
from django.test import TestCase
from emails.models import EmailJob, EmailJobStatus, EmailRecipientDelivery
from emails.outbox_service import EmailJobService
from users_roles.models import SystemRoleCode, User


class PublicAcademySignupTests(TestCase):
    endpoint = '/api/v1/auth/register/academy/'
    resend_endpoint = '/api/v1/auth/password/setup/resend/'

    def register(self, email='first-admin@example.com'):
        return self.client.post(
            self.endpoint,
            data=json.dumps({
                'academy_name': 'Technology Academy',
                'full_name': 'First Admin',
                'email': email,
                'phone': '+919876543210',
            }),
            content_type='application/json',
        )

    def test_registration_creates_admin_pending_setup_and_outbox_job(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()['success'])
        self.assertTrue(response.json()['data']['academy_uuid'])

        user = User.objects.get(email='first-admin@example.com')
        academy = Academy.objects.get(pk=user.academy_id)
        self.assertEqual(academy.name, 'Technology Academy')
        self.assertEqual(user.role_code, SystemRoleCode.ACADEMY_ADMIN)
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.password_setup_completed)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(
            AuthToken.objects.filter(user=user, token_type=TokenType.PASSWORD_SETUP).count(), 1
        )
        job = EmailJob.objects.get(template_name='academy_activation')
        self.assertEqual(job.status, EmailJobStatus.PENDING)
        self.assertEqual(job.academy_uuid, academy.id)
        self.assertEqual(job.metadata['recipient_email'], user.email)

    @patch('emails.outbox_service.send_transactional_email', return_value=True)
    @patch('credits.services.CreditsService.debit', side_effect=AssertionError('Security email must be free'))
    def test_activation_email_is_sent_without_wallet_credits(self, debit, send_email):
        response = self.register(email='fresh-admin@example.com')
        self.assertEqual(response.status_code, 201, response.content)
        job = EmailJob.objects.get(template_name='academy_activation')

        self.assertTrue(EmailJobService.process_email_job(str(job.id)))
        job.refresh_from_db()
        self.assertEqual(job.status, EmailJobStatus.SENT)
        self.assertEqual(
            EmailRecipientDelivery.objects.get(job=job).status, EmailJobStatus.SENT
        )
        send_email.assert_called_once()
        debit.assert_not_called()

    def test_duplicate_email_does_not_create_another_academy(self):
        self.assertEqual(self.register().status_code, 201)
        response = self.register()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Academy.objects.count(), 1)

    def test_invalid_registration_does_not_create_records(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps({'academy_name': '', 'full_name': '', 'email': 'invalid'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Academy.objects.count(), 0)

    def test_resend_regenerates_admin_password_setup_email(self):
        self.assertEqual(self.register().status_code, 201)
        user = User.objects.get(email='first-admin@example.com')
        response = self.client.post(
            self.resend_endpoint,
            data=json.dumps({'email': user.email}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            AuthToken.objects.filter(user=user, token_type=TokenType.PASSWORD_SETUP).count(), 2
        )
        self.assertEqual(EmailJob.objects.filter(template_name='academy_activation').count(), 2)
