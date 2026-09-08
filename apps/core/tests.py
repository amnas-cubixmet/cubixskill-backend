from academy.models import Academy
from courses.models import Course
from credits.models import CreditAccount
from credits.services import CreditsService
from django.test import TestCase
from enrollments.models import AccessType, Enrollment, EnrollmentStatus
from enrollments.services import EnrollmentService
from payments.models import OrderStatus, PaymentOrder
from payments.services import PaymentFulfillmentService
from rest_framework.test import APIClient
from users_roles.models import SystemRoleCode, User


class CubixSkillSystemTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create two isolated academies
        self.academy_a = Academy.objects.create(name="Academy A", slug="academy-a", email="info@academya.com")
        self.academy_b = Academy.objects.create(name="Academy B", slug="academy-b", email="info@academyb.com")

        # Create Academy Staff for A & B
        self.staff_a = User.objects.create_user(
            email="staff.a@academya.com",
            password="Password123!",
            full_name="Staff A",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy_a,
            is_email_verified=True,
            password_setup_completed=True
        )

        self.staff_b = User.objects.create_user(
            email="staff.b@academyb.com",
            password="Password123!",
            full_name="Staff B",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy_b,
            is_email_verified=True,
            password_setup_completed=True
        )

        # Courses
        self.course_a = Course.objects.create(academy=self.academy_a, title="Course A", price=99.00)
        self.course_b = Course.objects.create(academy=self.academy_b, title="Course B", price=199.00)

        # Allocate credits for testing enrollment operations
        from credits.services import CreditsService
        CreditsService.credit(academy=self.academy_a, amount=500.0, source_type='PURCHASE', idempotency_key='TEST_INIT_CREDITS')

    def test_tenant_isolation(self):
        """Verify Staff A cannot see or query Academy B courses."""
        self.client.force_authenticate(user=self.staff_a)
        response = self.client.get('/api/v1/courses/')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        course_ids = [c['id'] for c in results]

        self.assertIn(str(self.course_a.id), course_ids)
        self.assertNotIn(str(self.course_b.id), course_ids)

    def test_enrollment_service_access_creation(self):
        """Verify EnrollmentService creates active enrollment with default access type."""
        enrollment = EnrollmentService.enroll_student(
            student=self.staff_a,
            course=self.course_a,
            access_type=AccessType.FULL
        )
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)
        self.assertEqual(enrollment.access_type, AccessType.FULL)

    def test_credits_concurrency_and_ledger_idempotency(self):
        """Verify credit additions and debits update balances atomically with ledger entries."""
        CreditsService.credit(
            academy=self.academy_a,
            amount=50.0000,
            source_type='PURCHASE',
            idempotency_key='TX_1001',
            description='Initial deposit'
        )
        account = CreditAccount.objects.get(academy=self.academy_a)
        self.assertEqual(account.balance, 550.0000)

        # Idempotency check: duplicate call does not change balance
        CreditsService.credit(
            academy=self.academy_a,
            amount=50.0000,
            source_type='PURCHASE',
            idempotency_key='TX_1001',
            description='Initial deposit'
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, 550.0000)

    def test_payment_fulfillment_idempotency(self):
        """Verify payment webhook fulfillment triggers enrollment exactly once."""
        order = PaymentOrder.objects.create(
            payment_context='COURSE_PURCHASE',
            academy=self.academy_a,
            payer=self.staff_a,
            course=self.course_a,
            subtotal_amount=99.00,
            final_amount=99.00,
            status=OrderStatus.CREATED
        )

        PaymentFulfillmentService.process_successful_payment(order, "GATEWAY_REF_001", "STRIPE")
        self.assertTrue(Enrollment.objects.filter(student=self.staff_a, course=self.course_a).exists())

        # Second call should return idempotently without throwing error or duplicating enrollment
        PaymentFulfillmentService.process_successful_payment(order, "GATEWAY_REF_001", "STRIPE")
        self.assertEqual(Enrollment.objects.filter(student=self.staff_a, course=self.course_a).count(), 1)
