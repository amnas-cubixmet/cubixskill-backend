from decimal import Decimal

from academy.models import Academy
from courses.models import Course
from django.test import TestCase
from enrollments.models import Enrollment
from payments.encryption_service import decrypt_secret, encrypt_secret
from payments.models import (
    AcademyPaymentSettings,
    AcademySettlement,
    PaymentMode,
    SettlementStatus,
)
from payments.provider_resolver import resolve_payment_credentials
from rest_framework import status
from rest_framework.test import APIClient
from users_roles.models import Role, User


class DualPaymentArchitectureTestCase(TestCase):
    def setUp(self):
        # Create roles with code defaults
        self.instructor_role, _ = Role.objects.get_or_create(code='INSTRUCTOR', defaults={'name': 'Instructor'})
        self.student_role, _ = Role.objects.get_or_create(code='STUDENT', defaults={'name': 'Student'})

        # Create Academy A and Instructor A
        self.user_a = User.objects.create_user(
            email='instructor_a@example.com',
            password='password123',
            full_name='Instructor A',
            role_code='INSTRUCTOR'
        )
        self.academy_a = Academy.objects.create(
            name='Academy A',
            slug='academy-a'
        )
        self.user_a.academy = self.academy_a
        self.user_a.save()

        # Create Academy B and Instructor B
        self.user_b = User.objects.create_user(
            email='instructor_b@example.com',
            password='password123',
            full_name='Instructor B',
            role_code='INSTRUCTOR'
        )
        self.academy_b = Academy.objects.create(
            name='Academy B',
            slug='academy-b'
        )
        self.user_b.academy = self.academy_b
        self.user_b.save()

        from credits.models import CreditAccount
        CreditAccount.objects.get_or_create(academy=self.academy_a, defaults={'balance': Decimal('1000.00')})
        CreditAccount.objects.get_or_create(academy=self.academy_b, defaults={'balance': Decimal('1000.00')})

        # Create Student User
        self.student = User.objects.create_user(
            email='student@example.com',
            password='password123',
            full_name='Alice Student',
            role_code='STUDENT'
        )

        # Create Course in Academy A
        self.course_a = Course.objects.create(
            academy=self.academy_a,
            title='Production Python Masterclass',
            slug='production-python',
            price=Decimal('1500.00'),
            status='PUBLISHED'
        )

        self.client = APIClient()

    def test_encryption_and_decryption_service(self):
        secret = "secret_rzp_live_key_9999"
        encrypted = encrypt_secret(secret)
        self.assertNotEqual(secret, encrypted)
        decrypted = decrypt_secret(encrypted)
        self.assertEqual(secret, decrypted)

    def test_provider_resolver_mode1_academy_razorpay(self):
        # Configure Mode 1 for Academy A
        AcademyPaymentSettings.objects.create(
            academy=self.academy_a,
            payment_mode=PaymentMode.ACADEMY_RAZORPAY,
            razorpay_key_id='rzp_live_key_a_123',
            razorpay_key_secret_encrypted=encrypt_secret('secret_a_456'),
            razorpay_webhook_secret_encrypted=encrypt_secret('webhook_secret_a')
        )

        cred = resolve_payment_credentials(self.academy_a)
        self.assertEqual(cred['payment_mode'], PaymentMode.ACADEMY_RAZORPAY)
        self.assertEqual(cred['key_id'], 'rzp_live_key_a_123')
        self.assertEqual(cred['key_secret'], 'secret_a_456')
        self.assertEqual(cred['webhook_secret'], 'webhook_secret_a')

    def test_provider_resolver_mode2_cubixskill_central(self):
        # Configure Mode 2 for Academy B
        AcademyPaymentSettings.objects.create(
            academy=self.academy_b,
            payment_mode=PaymentMode.CUBIXSKILL_RAZORPAY
        )

        cred = resolve_payment_credentials(self.academy_b)
        self.assertEqual(cred['payment_mode'], PaymentMode.CUBIXSKILL_RAZORPAY)
        self.assertIn('rzp_', cred['key_id'])

    def test_secret_masking_in_settings_api(self):
        # Create settings with secret
        AcademyPaymentSettings.objects.create(
            academy=self.academy_a,
            payment_mode=PaymentMode.ACADEMY_RAZORPAY,
            razorpay_key_id='rzp_test_9999',
            razorpay_key_secret_encrypted=encrypt_secret('my_super_secret_key')
        )

        self.client.force_authenticate(user=self.user_a)
        res = self.client.get('/api/v1/payments/settings/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.json()['data']
        self.assertEqual(data['key_secret_preview'], '••••••••••••••••')
        self.assertNotIn('my_super_secret_key', str(data))

    def test_tenant_isolation_payment_settings(self):
        # User B tries to view or update User A's payment settings via endpoint
        self.client.force_authenticate(user=self.user_b)
        res = self.client.get('/api/v1/payments/settings/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Ensures returned settings belong to Academy B
        data = res.json()['data']
        settings_b = AcademyPaymentSettings.objects.get(academy=self.academy_b)
        self.assertEqual(data['id'], str(settings_b.id))

    def test_order_creation_and_signature_verification_enrollment(self):
        # 1. Order Creation
        self.client.force_authenticate(user=self.student)
        res_order = self.client.post('/api/v1/payments/orders/', {
            'academy_uuid': str(self.academy_a.pk),
            'course_uuid': str(self.course_a.id)
        }, format='json')
        self.assertEqual(res_order.status_code, status.HTTP_201_CREATED)
        order_data = res_order.json()['order']

        rzp_order_id = order_data['razorpay_order_id']
        self.assertTrue(rzp_order_id)

        # 2. Signature Verification & Automatic Enrollment Activation
        res_verify = self.client.post('/api/v1/payments/verify/', {
            'razorpay_payment_id': 'pay_test_rzp_12345',
            'razorpay_order_id': rzp_order_id,
            'razorpay_signature': 'mock_sig_valid'
        }, format='json')
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)

        # Check Enrollment is activated
        enrolled = Enrollment.objects.filter(student=self.student, course=self.course_a, status='ACTIVE').exists()
        self.assertTrue(enrolled)

        # Check Settlement entry created for Mode 2
        settlements = AcademySettlement.objects.filter(academy=self.academy_a)
        self.assertEqual(settlements.count(), 1)
        self.assertEqual(settlements.first().status, SettlementStatus.PENDING)
