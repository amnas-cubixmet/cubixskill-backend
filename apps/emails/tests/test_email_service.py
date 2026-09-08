from academy.models import Academy, AcademyStatus
from authentication.models import AuthTokenService, TokenType
from django.core import mail
from django.test import TestCase
from emails.services import (
    send_academy_activation_email,
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
)
from users_roles.models import SystemRoleCode, User


class EmailServiceTestCase(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(
            name="Apex Learning Academy",
            email="info@apexlearning.io",
            status=AcademyStatus.ACTIVE,
            is_active=True
        )
        self.user = User.objects.create_user(
            email="admin@apexlearning.io",
            full_name="Dr. Apex Admin",
            role_code=SystemRoleCode.ACADEMY_ADMIN,
            academy=self.academy,
            is_email_verified=False,
            password_setup_completed=False
        )
        from decimal import Decimal

        from credits.services import CreditsService
        account = CreditsService.get_or_create_account(self.academy)
        account.balance = Decimal('100.0000')
        account.save(update_fields=['balance'])

    def test_send_academy_activation_email(self):
        from emails.outbox_service import EmailJobService
        token = AuthTokenService.generate_token(self.user, TokenType.PASSWORD_SETUP)
        job = send_academy_activation_email(self.user, self.academy, token)

        self.assertIsNotNone(job)
        EmailJobService.process_email_job(str(job.id))
        self.assertEqual(len(mail.outbox), 1)

        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.to, ["admin@apexlearning.io"])
        self.assertIn("Activate Your CubixSkill Academy Account", sent_mail.subject)

        # Verify HTML alternative
        self.assertEqual(len(sent_mail.alternatives), 1)
        html_body, mime_type = sent_mail.alternatives[0]
        self.assertEqual(mime_type, "text/html")
        self.assertIn("/setup-password?token=", html_body)

    def test_send_password_reset_email(self):
        from emails.outbox_service import EmailJobService
        token = AuthTokenService.generate_token(self.user, TokenType.PASSWORD_RESET)
        job = send_password_reset_email(self.user, token)

        self.assertIsNotNone(job)
        EmailJobService.process_email_job(str(job.id))
        self.assertEqual(len(mail.outbox), 1)

        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.to, ["admin@apexlearning.io"])
        self.assertIn("Reset Your CubixSkill Password", sent_mail.subject)
        html_body, _ = sent_mail.alternatives[0]
        self.assertIn("/reset-password?token=", html_body)

    def test_send_password_changed_email(self):
        from emails.outbox_service import EmailJobService
        job = send_password_changed_email(self.user)

        self.assertIsNotNone(job)
        EmailJobService.process_email_job(str(job.id))
        self.assertEqual(len(mail.outbox), 1)

        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.to, ["admin@apexlearning.io"])
        self.assertIn("Password Has Been Changed", sent_mail.subject)

    def test_send_verification_email(self):
        from emails.outbox_service import EmailJobService
        token = AuthTokenService.generate_token(self.user, TokenType.EMAIL_VERIFICATION)
        job = send_verification_email(self.user, token)

        self.assertIsNotNone(job)
        EmailJobService.process_email_job(str(job.id))
        self.assertEqual(len(mail.outbox), 1)

        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.to, ["admin@apexlearning.io"])
        self.assertIn("Verify Your Email", sent_mail.subject)
        html_body, _ = sent_mail.alternatives[0]
        self.assertIn("/verify-email?token=", html_body)

    def test_resend_email_single_use_token_behavior(self):
        # Generate initial token
        token1 = AuthTokenService.generate_token(self.user, TokenType.PASSWORD_SETUP)
        # Resend triggers new token generation
        token2 = AuthTokenService.generate_token(self.user, TokenType.PASSWORD_SETUP)

        # token1 should be invalidated (revoked), token2 should be valid
        user_from_token1 = AuthTokenService.validate_token_peek(token1, TokenType.PASSWORD_SETUP)
        user_from_token2 = AuthTokenService.validate_token_peek(token2, TokenType.PASSWORD_SETUP)

        self.assertIsNone(user_from_token1)
        self.assertEqual(user_from_token2, self.user)
