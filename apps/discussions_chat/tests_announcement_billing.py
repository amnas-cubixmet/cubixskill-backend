from decimal import Decimal
from django.test import TestCase
from academy.models import Academy
from django.contrib.auth import get_user_model
from courses.models import Course
from enrollments.models import Enrollment
from discussions_chat.models import DiscussionThread, ThreadType
from discussions_chat.services import DiscussionService
from credits.models import CreditAccount, CreditLedgerEntry, CreditSourceType
from control_panel.models import PricingRule
from core.exceptions import CubixSkillAPIException

User = get_user_model()

class AnnouncementBillingTestCase(TestCase):
    def setUp(self):
        # Create academy owner and academy
        self.owner = User.objects.create_user(
            email="owner@academy.com",
            password="password123"
        )
        self.academy = Academy.objects.create(
            name="Announcement Test Academy",
            slug="announcement-test-academy"
        )
        self.owner.academy = self.academy
        self.owner.save()
        # Create credit account with 100 credits
        self.credit_account = CreditAccount.objects.create(
            academy=self.academy,
            balance=Decimal('100.000000')
        )
        # Set up central Super Admin pricing rules
        PricingRule.objects.update_or_create(
            code='COURSE_ANNOUNCEMENT',
            defaults={
                'name': 'Course Announcement',
                'category': 'FEATURE PRICING',
                'billing_unit': 'PER_ANNOUNCEMENT',
                'credit_cost': 2,
                'is_active': True
            }
        )
        PricingRule.objects.update_or_create(
            code='EMAIL_DELIVERY',
            defaults={
                'name': 'Email Delivery',
                'category': 'FEATURE PRICING',
                'billing_unit': 'PER_EMAIL',
                'credit_cost': 1, # Using 1 for simple math in tests or Decimal rates
                'is_active': True
            }
        )

        # Create course & students
        self.course = Course.objects.create(
            academy=self.academy,
            title="React 19 Architecture",
            slug="react-19-architecture"
        )
        
        # Enrolled student 1 with valid email
        self.student1 = User.objects.create_user(
            email="student1@test.com",
            password="password123",
            academy=self.academy
        )
        Enrollment.objects.create(student=self.student1, course=self.course, status="ACTIVE")

        # Enrolled student 2 with valid email
        self.student2 = User.objects.create_user(
            email="student2@test.com",
            password="password123",
            academy=self.academy
        )
        Enrollment.objects.create(student=self.student2, course=self.course, status="ACTIVE")

    def test_1_draft_announcement_no_credit_deduction(self):
        """1. Saving draft announcement deducts 0 credits."""
        thread = DiscussionService.create_thread(
            course=self.course,
            user=self.owner,
            title="Draft Announcement",
            content="This is a draft content",
            thread_type=ThreadType.ANNOUNCEMENT,
            send_email=True,
            publish_option="draft"
        )
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('100.000000'))
        self.assertFalse(thread.credit_charge_applied)
        self.assertEqual(thread.announcement_credits_charged, Decimal('0.000000'))

    def test_2_publish_email_off_deducts_announcement_price_only(self):
        """2. Publish + Email OFF -> Announcement charge only (2 credits)."""
        thread = DiscussionService.create_thread(
            course=self.course,
            user=self.owner,
            title="Publish Email OFF",
            content="Announcement body",
            thread_type=ThreadType.ANNOUNCEMENT,
            send_email=False,
            publish_option="now"
        )
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('98.000000'))
        self.assertTrue(thread.credit_charge_applied)
        self.assertEqual(thread.announcement_credits_charged, Decimal('2.000000'))
        self.assertEqual(thread.email_credits_charged, Decimal('0.000000'))

        # Check ledger: 1 entry created
        ledger = CreditLedgerEntry.objects.filter(account=self.credit_account)
        self.assertEqual(ledger.count(), 1)
        self.assertEqual(ledger.first().amount, Decimal('2.000000'))

    def test_3_and_4_publish_email_on_deducts_announcement_plus_email_cost(self):
        """3 & 4. Publish + Email ON -> Announcement charge (2) + Email charge (2 students x 1 = 2) = 4 credits."""
        thread = DiscussionService.create_thread(
            course=self.course,
            user=self.owner,
            title="Publish Email ON",
            content="Announcement with email",
            thread_type=ThreadType.ANNOUNCEMENT,
            send_email=True,
            publish_option="now"
        )
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('96.000000')) # 100 - 2 - 2 = 96
        self.assertEqual(thread.email_recipient_count, 2)

        # Separate ledger entries created
        ledger_entries = list(CreditLedgerEntry.objects.filter(account=self.credit_account).order_by('created_at'))
        self.assertEqual(len(ledger_entries), 2)
        # Entry 1: ANNOUNCEMENT
        self.assertEqual(ledger_entries[0].amount, Decimal('2.000000'))
        # Entry 2: EMAIL_DELIVERY
        self.assertEqual(ledger_entries[1].amount, Decimal('2.000000'))
        self.assertEqual(ledger_entries[1].source_type, CreditSourceType.EMAIL_USAGE)

    def test_5_zero_eligible_email_recipients(self):
        """5. Email ON but 0 eligible recipients -> 0 email charge, announcement charged."""
        empty_course = Course.objects.create(academy=self.academy, title="Empty Course", slug="empty-course")
        thread = DiscussionService.create_thread(
            course=empty_course,
            user=self.owner,
            title="No Students",
            content="Content",
            thread_type=ThreadType.ANNOUNCEMENT,
            send_email=True,
            publish_option="now"
        )
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('98.000000')) # 100 - 2 = 98
        self.assertEqual(thread.email_recipient_count, 0)
        self.assertEqual(thread.email_credits_charged, Decimal('0.000000'))

    def test_6_insufficient_credits_blocks_publication(self):
        """6. Balance = 1, total cost = 4 -> publication rejected, balance stays 1, 0 deductions."""
        self.credit_account.balance = Decimal('1.000000')
        self.credit_account.save()

        with self.assertRaises(CubixSkillAPIException) as ctx:
            DiscussionService.create_thread(
                course=self.course,
                user=self.owner,
                title="Insufficient Credits Test",
                content="Content",
                thread_type=ThreadType.ANNOUNCEMENT,
                send_email=True,
                publish_option="now"
            )

        self.assertIn("Insufficient academy credits", str(ctx.exception))
        self.credit_account.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('1.000000'))

    def test_7_tenant_isolation(self):
        """7. Academy A announcement deducts Academy A credits; Academy B balance unchanged."""
        academy_b = Academy.objects.create(name="Academy B", slug="academy-b")
        account_b = CreditAccount.objects.create(academy=academy_b, balance=Decimal('100.000000'))

        DiscussionService.create_thread(
            course=self.course, # Course in Academy A
            user=self.owner,
            title="Academy A Announcement",
            content="Content",
            thread_type=ThreadType.ANNOUNCEMENT,
            send_email=False,
            publish_option="now"
        )

        self.credit_account.refresh_from_db()
        account_b.refresh_from_db()
        self.assertEqual(self.credit_account.balance, Decimal('98.000000'))
        self.assertEqual(account_b.balance, Decimal('100.000000'))
