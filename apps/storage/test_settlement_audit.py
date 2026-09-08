from decimal import Decimal

from academy.models import Academy
from credits.models import CreditAccount
from credits.services import CreditService
from django.test import TestCase
from storage.models import (
    AcademyStorageUsage,
    MediaFile,
    MediaStatus,
    MediaType,
    StorageBillingCycle,
    StorageBillingCycleStatus,
    StorageBillingSettings,
    StorageMeterFileSnapshot,
    StorageMeterRecord,
)
from storage.services import StorageOutstandingService, StorageSettlementService
from storage.tasks import meter_due_storage_usage


class EventDrivenSettlementAndAuditTests(TestCase):
    def setUp(self):
        self.setting = StorageBillingSettings.get_settings()
        self.setting.storage_billing_enabled = True
        self.setting.storage_billing_interval = "10_SECONDS"
        self.setting.storage_credit_rate_per_gb = Decimal("10.0000")
        self.setting.save()

        self.academy_a = Academy.objects.create(name="Cassandra Academy", slug="cassandra-academy", email="cassandra@test.com")
        self.credit_acc_a = CreditAccount.objects.create(academy=self.academy_a, balance=Decimal("819.0000"))

        self.academy_b = Academy.objects.create(name="Beta Academy", slug="beta-academy", email="beta@test.com")
        self.credit_acc_b = CreditAccount.objects.create(academy=self.academy_b, balance=Decimal("100.0000"))

        self.media_file_a1 = MediaFile.objects.create(
            academy_uuid=self.academy_a.id,
            original_filename="intro_video.mp4",
            display_name="Intro Video",
            media_type=MediaType.VIDEO,
            size_bytes=1073741824, # 1 GB
            status=MediaStatus.ACTIVE
        )

        AcademyStorageUsage.objects.create(
            academy=self.academy_a,
            academy_uuid=self.academy_a.id,
            used_bytes=1073741824,
            file_count=1
        )

    def test_metering_increases_cycle_credits_without_debiting_account_balance(self):
        """Req 1 & 2: Metering increases OPEN cycle accumulated credits without debiting credit balance."""
        bal_before = CreditService.get_balance(self.academy_a)

        meter_due_storage_usage()

        bal_after = CreditService.get_balance(self.academy_a)
        self.assertEqual(bal_before, bal_after)

        open_cycle = StorageBillingCycle.objects.filter(
            academy=self.academy_a, status=StorageBillingCycleStatus.OPEN
        ).first()
        self.assertIsNotNone(open_cycle)
        self.assertGreater(open_cycle.accumulated_credits, Decimal("0.0000"))

    def test_metering_creates_file_snapshot(self):
        """Req 10: File active during meter appears in StorageMeterFileSnapshot."""
        meter_due_storage_usage()

        meter_rec = StorageMeterRecord.objects.filter(academy=self.academy_a).first()
        self.assertIsNotNone(meter_rec)

        snapshots = list(StorageMeterFileSnapshot.objects.filter(meter_record=meter_rec))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].filename_snapshot, "Intro Video")
        self.assertEqual(snapshots[0].media_file_uuid, self.media_file_a1.id)

    def test_deleted_file_remains_in_historical_snapshots_and_excluded_from_future_meters(self):
        """Req 11 & 12: Deleted file remains in historical snapshot and disappears from future meters."""
        # Meter 1: File active
        meter_due_storage_usage()
        meter_rec1 = StorageMeterRecord.objects.filter(academy=self.academy_a).order_by('created_at').first()
        self.assertEqual(StorageMeterFileSnapshot.objects.filter(meter_record=meter_rec1).count(), 1)

        # Delete file
        self.media_file_a1.status = MediaStatus.DELETED
        self.media_file_a1.save()

        usage = AcademyStorageUsage.objects.get(academy=self.academy_a)
        usage.used_bytes = 0
        usage.file_count = 0
        usage.last_billed_at = None # allow next meter
        usage.save()

        # Meter 2: File deleted
        meter_due_storage_usage()
        meter_rec2 = StorageMeterRecord.objects.filter(academy=self.academy_a).order_by('-created_at').first()

        # Meter 1 snapshot still has file
        self.assertEqual(StorageMeterFileSnapshot.objects.filter(meter_record=meter_rec1).count(), 1)

        # Meter 2 snapshot has 0 files
        self.assertEqual(StorageMeterFileSnapshot.objects.filter(meter_record=meter_rec2).count(), 0)

    def test_monthly_settlement_debits_once_resets_cycle_and_starts_new_open_cycle(self):
        """Req 4, 8, 9, 28: Monthly settlement debits credit account, closes cycle, and starts new OPEN cycle."""
        meter_due_storage_usage()

        open_cycle = StorageBillingCycle.objects.filter(
            academy=self.academy_a, status=StorageBillingCycleStatus.OPEN
        ).first()
        accumulated = open_cycle.accumulated_credits
        self.assertGreater(accumulated, Decimal("0.0000"))

        initial_bal = CreditService.get_balance(self.academy_a)

        # Settle cycle
        settled_cycle, success = StorageSettlementService.settle_cycle(open_cycle)
        self.assertTrue(success)
        self.assertEqual(settled_cycle.status, StorageBillingCycleStatus.SETTLED)

        # Check balance reduced
        final_bal = CreditService.get_balance(self.academy_a)
        self.assertEqual(final_bal, initial_bal - accumulated)

        # Check new OPEN cycle created starting at 0
        new_open_cycle = StorageBillingCycle.objects.filter(
            academy=self.academy_a, status=StorageBillingCycleStatus.OPEN
        ).first()
        self.assertIsNotNone(new_open_cycle)
        self.assertEqual(new_open_cycle.accumulated_credits, Decimal("0.0000"))

    def test_partial_settlement_creates_outstanding_balance(self):
        """Req 7 & 8: Partial settlement sets credit balance to zero and creates outstanding debt."""
        # Set low credit balance
        self.credit_acc_a.balance = Decimal("5.0000")
        self.credit_acc_a.save()

        meter_due_storage_usage()

        cycle = StorageBillingCycle.objects.filter(academy=self.academy_a, status=StorageBillingCycleStatus.OPEN).first()
        self.assertIsNotNone(cycle)
        cycle.accumulated_credits = Decimal("10.0000")
        cycle.save()

        settled_cycle, success = StorageSettlementService.settle_cycle(cycle)
        self.assertTrue(success)

        # Balance reduced to 0
        self.assertEqual(CreditService.get_balance(self.academy_a), Decimal("0.0000"))

        # Paid = 5, Outstanding = 5
        self.assertEqual(settled_cycle.paid_amount, Decimal("5.0000"))
        self.assertEqual(settled_cycle.outstanding_amount, Decimal("5.0000"))
        self.assertEqual(StorageOutstandingService.get_total_outstanding_credits(self.academy_a), Decimal("5.0000"))
