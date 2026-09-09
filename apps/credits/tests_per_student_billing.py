from decimal import Decimal
from django.test import TestCase
from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from features.models import Feature, CourseFeature
from features.services import CourseFeatureService
from credits.models import CreditAccount, CourseFeatureBilledStudent
from credits.services import CreditPricingService, CreditsService
from enrollments.services import EnrollmentService
from control_panel.models import PricingRule, PricingService


class PerStudentBillingTestCase(TestCase):
    def setUp(self):
        CourseFeatureService.ensure_default_features()
        PricingService.ensure_default_rules()

        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy")
        self.account = CreditsService.get_or_create_account(self.academy)
        CreditsService.credit(
            academy=self.academy,
            amount=Decimal('10000.000000'),
            source_type="PURCHASE",
            idempotency_key="setup_credits"
        )

        self.course = Course.objects.create(
            academy=self.academy,
            title="Python Masterclass",
            slug="python-masterclass"
        )

        self.student1 = User.objects.create(
            email="student1@example.com",
            full_name="Student One",
            academy=self.academy,
            role_code="STUDENT"
        )
        self.student2 = User.objects.create(
            email="student2@example.com",
            full_name="Student Two",
            academy=self.academy,
            role_code="STUDENT"
        )

    def test_combined_per_student_cost_calculation(self):
        # 1. Disable all features first
        for feat in Feature.objects.filter(is_active=True):
            CourseFeatureService.disable_feature(self.course, feat.code)

        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 0)

        # 2. Lessons ON = 100, Fee Collection OFF => 100 Credits / Student
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 100)

        # 3. Lessons ON (100) + Fee Collection ON (2) => 102 Credits / Student
        CourseFeatureService.enable_feature(self.course, 'FEE_COLLECTION')
        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 102)

        # 4. Lessons OFF + Fee Collection ON => 2 Credits / Student
        CourseFeatureService.disable_feature(self.course, 'LESSONS')
        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 2)

        # 5. Non-PER_STUDENT features ON (Announcement, Email, Certificate) => do NOT change total
        CourseFeatureService.enable_feature(self.course, 'COURSE_ANNOUNCEMENT')
        CourseFeatureService.enable_feature(self.course, 'EMAIL_DELIVERY')
        CourseFeatureService.enable_feature(self.course, 'COMPLETION_CERTIFICATE')
        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 2)

        # 6. Free features ON (Live Class, Discussion) => do NOT change total
        CourseFeatureService.enable_feature(self.course, 'LIVE_CLASS')
        CourseFeatureService.enable_feature(self.course, 'COURSE_DISCUSSION')
        pricing = CreditPricingService.get_course_per_student_credit_cost(self.course)
        self.assertEqual(pricing["total_per_student_credits"], 2)

    def test_single_student_enrollment_deduction(self):
        # Enable Lessons (100) + Fee Collection (2) => 102
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        CourseFeatureService.enable_feature(self.course, 'FEE_COLLECTION')

        bal_before = CreditsService.get_balance(self.academy)
        EnrollmentService.enroll_student(self.student1, self.course)
        bal_after = CreditsService.get_balance(self.academy)

        self.assertEqual(bal_before - bal_after, Decimal('102.000000'))

    def test_bulk_student_enrollment_deduction(self):
        # Enable Lessons (100) + Fee Collection (2) => 102
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        CourseFeatureService.enable_feature(self.course, 'FEE_COLLECTION')

        students = []
        for i in range(10):
            st = User.objects.create(
                email=f"bulk_student_{i}@example.com",
                full_name=f"Bulk Student {i}",
                academy=self.academy,
                role_code="STUDENT"
            )
            students.append(st)

        bal_before = CreditsService.get_balance(self.academy)
        EnrollmentService.charge_enrollment_per_student_credits(self.course, students)
        bal_after = CreditsService.get_balance(self.academy)

        # 10 x 102 = 1020
        self.assertEqual(bal_before - bal_after, Decimal('1020.000000'))

    def test_duplicate_enrollment_no_duplicate_charge(self):
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        CourseFeatureService.enable_feature(self.course, 'FEE_COLLECTION')

        bal1 = CreditsService.get_balance(self.academy)
        EnrollmentService.enroll_student(self.student1, self.course)
        bal2 = CreditsService.get_balance(self.academy)

        self.assertEqual(bal1 - bal2, Decimal('102.000000'))

        # Enroll same student again
        EnrollmentService.enroll_student(self.student1, self.course)
        bal3 = CreditsService.get_balance(self.academy)

        # Balance remains unchanged
        self.assertEqual(bal2, bal3)

    def test_feature_enabled_later_only_charges_new_feature(self):
        # 1. Enroll student when only Lessons (100) is ON
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        CourseFeatureService.disable_feature(self.course, 'FEE_COLLECTION')

        bal1 = CreditsService.get_balance(self.academy)
        EnrollmentService.enroll_student(self.student1, self.course)
        bal2 = CreditsService.get_balance(self.academy)

        self.assertEqual(bal1 - bal2, Decimal('100.000000'))

        # 2. Later, enable Fee Collection (2)
        CourseFeatureService.enable_feature(self.course, 'FEE_COLLECTION')

        # 3. Apply enrollment check for existing student
        EnrollmentService.charge_enrollment_per_student_credits(self.course, [self.student1])
        bal3 = CreditsService.get_balance(self.academy)

        # Only 2 credits deducted for Fee Collection, Lessons (100) not charged again
        self.assertEqual(bal2 - bal3, Decimal('2.000000'))

    def test_disable_re_enable_no_double_charge(self):
        CourseFeatureService.enable_feature(self.course, 'LESSONS')
        EnrollmentService.enroll_student(self.student1, self.course)

        bal1 = CreditsService.get_balance(self.academy)

        # Disable and re-enable Lessons
        CourseFeatureService.disable_feature(self.course, 'LESSONS')
        CourseFeatureService.enable_feature(self.course, 'LESSONS')

        EnrollmentService.charge_enrollment_per_student_credits(self.course, [self.student1])
        bal2 = CreditsService.get_balance(self.academy)

        # Student was already charged for Lessons entitlement; no charge
        self.assertEqual(bal1, bal2)
