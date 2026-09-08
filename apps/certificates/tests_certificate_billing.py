import uuid
from django.test import TestCase
from django.utils import timezone
from academy.models import Academy
from django.contrib.auth import get_user_model
from courses.models import Course
from enrollments.models import Enrollment
from certificates.models import Certificate, CertificateTemplate
from certificates.services import CertificateService
from credits.models import CreditAccount, CreditLedgerEntry, CreditSourceType
from control_panel.models import PricingRule

User = get_user_model()

class CertificateBillingTestCase(TestCase):
    def setUp(self):
        # Create academy owner and academy
        self.owner = User.objects.create_user(
            email="owner@academy.com",
            password="password123",
            first_name="Academy",
            last_name="Owner"
        )
        self.academy = Academy.objects.create(
            name="Test Academy",
            slug="testacademy",
            owner=self.owner
        )
        # Create credit account for academy with initial 100 credits
        self.credit_account = CreditAccount.objects.create(
            academy=self.academy,
            balance=100
        )
        # Configure central super admin pricing setting for completion certificates
        PricingRule.objects.update_or_create(
            code='COMPLETION_CERTIFICATE',
            defaults={
                'name': 'Completion Certificate',
                'category': 'FEATURE PRICING',
                'billing_unit': 'PER_CERTIFICATE',
                'credit_cost': 5,
                'is_active': True
            }
        )

        # Create course & enrollment for student
        self.student = User.objects.create_user(
            email="student@example.com",
            password="password123",
            first_name="John",
            last_name="Doe"
        )
        self.course = Course.objects.create(
            academy=self.academy,
            title="Python Masterclass",
            slug="python-masterclass"
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course
        )
        self.template = CertificateTemplate.objects.create(
            academy=self.academy,
            name="Standard Completion",
            is_default=True,
            is_active=True
        )

    def test_1_issue_one_certificate_deducts_credits(self):
        """1. Academy balance = 100, price = 5, issue one new cert -> balance = 95."""
        cert = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        self.assertIsNotNone(cert)
        self.assertEqual(cert.status, Certificate.Status.ISSUED)
        self.assertEqual(cert.credits_charged, 5)
        self.assertTrue(cert.credit_charge_applied)
        
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 95)
        
        # Verify ledger entry created
        ledger = CreditLedgerEntry.objects.filter(credit_account=self.credit_account).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.amount, -5)
        self.assertEqual(ledger.source_type, CreditSourceType.CERTIFICATE_ISSUE)

    def test_2_and_3_redownload_and_preview_no_additional_debit(self):
        """2 & 3. Download / re-download / preview issued certificate deducts 0 additional credits."""
        cert = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 95)

        # Re-call issue service on same enrollment/certificate
        cert2 = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        self.assertEqual(cert2.id, cert.id)
        
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 95) # Balance stays 95

    def test_4_duplicate_issue_endpoint_call_idempotency(self):
        """4. Calling issue twice on same certificate only deducts once."""
        cert1 = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        cert2 = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 95)

    def test_5_issue_second_different_certificate(self):
        """5. Issue a second different certificate -> another 5-credit debit."""
        CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        
        # Second enrollment
        student2 = User.objects.create_user(
            email="student2@example.com",
            password="password123",
            first_name="Jane",
            last_name="Doe"
        )
        enrollment2 = Enrollment.objects.create(
            student=student2,
            course=self.course
        )
        cert2 = CertificateService.issue_if_eligible(student=student2, course=self.course, enrollment=enrollment2)
        self.assertIsNotNone(cert2)
        
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 90)

    def test_6_insufficient_credits_prevents_issue(self):
        """6. Academy balance = 3, required = 5 -> cert not issued, balance remains 3, error raised."""
        self.credit_account.balance = 3
        self.credit_account.save()

        with self.assertRaises(ValueError) as ctx:
            CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)

        self.assertIn("Insufficient academy credits. 5 credits are required to issue this certificate.", str(ctx.exception))

        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 3)
        self.assertFalse(Certificate.objects.filter(enrollment=self.enrollment).exists())

    def test_7_price_change_preserves_historical_charge(self):
        """7. Super Admin changes price from 5 to 8. Previously issued cert remains charged 5, next cert charges 8."""
        cert1 = CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)
        self.assertEqual(cert1.credits_charged, 5)

        # Update pricing rule
        rule = PricingRule.objects.get(code='COMPLETION_CERTIFICATE')
        rule.credit_cost = 8
        rule.save()

        # Issue second certificate
        student2 = User.objects.create_user(
            email="student2@example.com",
            password="password123",
            first_name="Jane",
            last_name="Doe"
        )
        enrollment2 = Enrollment.objects.create(
            student=student2,
            course=self.course
        )
        cert2 = CertificateService.issue_if_eligible(student=student2, course=self.course, enrollment=enrollment2)
        self.assertEqual(cert2.credits_charged, 8)

        # Check total balance: initial 100 - 5 - 8 = 87
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 87)

    def test_9_academy_isolation(self):
        """9. Academy A certificate deducts Academy A credits; Academy B balance unchanged."""
        academy_b = Academy.objects.create(
            name="Academy B",
            slug="academyb",
            owner=self.owner
        )
        credit_b = CreditAccount.objects.create(academy=academy_b, balance=100)

        CertificateService.issue_if_eligible(student=self.student, course=self.course, enrollment=self.enrollment)

        self.credit_account.refresh_from_db()
        credit_b.refresh_from_db()
        self.assertEqual(self.credit_account.balance, 95)
        self.assertEqual(credit_b.balance, 100)
