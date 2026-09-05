import os
import subprocess
import uuid
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile
from academy.models import Academy
from users_roles.models import User, SystemRoleCode
from storage.models import (
    MediaFile, MediaStatus, MediaType, AcademyStorageAccount,
    StorageUsageEvent, StorageMonthlyBilling, BillingStatus, UsageEventType
)
from storage.services import StorageService
from storage.metering import StorageMeteringService, StorageBillingService
from credits.services import CreditService
from credits.models import CreditAccount, LedgerEntryType, CreditSourceType
from courses.models import Course

class StorageServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy", email="info@test.com")
        self.user = User.objects.create_user(
            email="staff@test.com",
            password="Password123!",
            full_name="Staff User",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy,
            is_email_verified=True,
            password_setup_completed=True
        )

        self.academy_b = Academy.objects.create(name="Academy B", slug="academy-b", email="info@b.com")
        self.user_b = User.objects.create_user(
            email="staff@b.com",
            password="Password123!",
            full_name="Staff B User",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy_b,
            is_email_verified=True,
            password_setup_completed=True
        )

        # Ensure CreditAccount exists with 1000 credits for testing
        CreditService.credit(
            academy=self.academy,
            amount=Decimal('1000.000000'),
            source_type=CreditSourceType.PROMOTIONAL,
            idempotency_key=f"test_init:{self.academy.id}"
        )

    def test_direct_local_media_upload_service(self):
        """Verify uploading file to local MEDIA_ROOT folder inside per-Academy directory."""
        dummy_file = SimpleUploadedFile("test_document.pdf", b"PDF dummy content", content_type="application/pdf")

        media_file = StorageService.upload_media_direct(
            academy_uuid=self.academy.id,
            user_uuid=self.user.id,
            file_obj=dummy_file,
            original_filename="test_document.pdf",
            mime_type="application/pdf",
            file_size_bytes=len(b"PDF dummy content")
        )

        self.assertEqual(media_file.academy_uuid, self.academy.id)
        self.assertEqual(media_file.media_type, MediaType.DOCUMENT)
        self.assertEqual(media_file.status, MediaStatus.ACTIVE)

        # Check physical file path on local disk
        expected_folder = os.path.normpath(os.path.join(settings.MEDIA_ROOT, 'academies', str(self.academy.id), 'documents'))
        actual_path = os.path.normpath(media_file.storage_path)
        self.assertTrue(actual_path.startswith(expected_folder))
        self.assertTrue(os.path.exists(actual_path))

        # Verify storage accounting updated in PostgreSQL
        account = AcademyStorageAccount.objects.get(academy_uuid=self.academy.id)
        self.assertEqual(account.current_usage_bytes, media_file.size_bytes)

        # Clean up created file
        if os.path.exists(media_file.storage_path):
            os.remove(media_file.storage_path)

    def test_delete_media_file_removes_local_file_and_updates_postgres(self):
        """Verify deleting media file cleans up local physical file and updates PostgreSQL."""
        dummy_image = SimpleUploadedFile("avatar.png", b"PNG dummy bytes", content_type="image/png")
        media_file = StorageService.upload_media_direct(
            academy_uuid=self.academy.id,
            user_uuid=self.user.id,
            file_obj=dummy_image,
            original_filename="avatar.png",
            mime_type="image/png",
            file_size_bytes=len(b"PNG dummy bytes")
        )

        local_path = media_file.storage_path
        self.assertTrue(os.path.exists(local_path))

        StorageService.delete_media_file(media_file, hard_delete=False)

        self.assertFalse(os.path.exists(local_path))
        media_file.refresh_from_db()
        self.assertEqual(media_file.status, MediaStatus.DELETED)

        # Verify usage updated in PostgreSQL
        account = AcademyStorageAccount.objects.get(academy_uuid=self.academy.id)
        self.assertEqual(account.current_usage_bytes, 0)

    def test_unused_file_usage_endpoint_returns_200(self):
        """Unused valid file must return HTTP 200 OK with is_used=False and references=[]."""
        self.client.force_authenticate(user=self.user)
        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.user.id,
            original_filename="unused_file.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            storage_key=f"academies/{self.academy.id}/documents/unused.pdf"
        )

        url = f"/api/v1/storage/files/{media_file.id}/usage/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json().get('data', {})
        self.assertEqual(data.get('file_id'), str(media_file.id))
        self.assertFalse(data.get('is_used'))
        self.assertEqual(data.get('usage_count'), 0)
        self.assertEqual(data.get('references'), [])

    def test_used_file_usage_endpoint_returns_200_with_references(self):
        """Used file must return HTTP 200 OK with is_used=True and real reference items."""
        self.client.force_authenticate(user=self.user)
        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.user.id,
            original_filename="course_banner.png",
            mime_type="image/png",
            size_bytes=2048,
            storage_key=f"academies/{self.academy.id}/images/banner.png"
        )

        # Attach as Course thumbnail
        course = Course.objects.create(
            academy=self.academy,
            title="Python Mastery",
            thumbnail=media_file
        )

        url = f"/api/v1/storage/files/{media_file.id}/usage/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json().get('data', {})
        self.assertTrue(data.get('is_used'))
        self.assertEqual(data.get('usage_count'), 1)
        refs = data.get('references', [])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['type'], 'COURSE')
        self.assertEqual(refs[0]['title'], 'Python Mastery')

    def test_cross_academy_file_usage_returns_404(self):
        """Academy A user attempting to inspect Academy B file usage must get 404."""
        media_file_b = MediaFile.objects.create(
            academy_uuid=self.academy_b.id,
            uploaded_by_uuid=self.user_b.id,
            original_filename="private_b.png",
            mime_type="image/png",
            size_bytes=512,
            storage_key=f"academies/{self.academy_b.id}/images/b.png"
        )

        self.client.force_authenticate(user=self.user)  # User A
        url = f"/api/v1/storage/files/{media_file_b.id}/usage/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_file_usage_returns_404(self):
        """Random non-existent UUID must return 404 Not Found."""
        self.client.force_authenticate(user=self.user)
        random_uuid = uuid.uuid4()
        url = f"/api/v1/storage/files/{random_uuid}/usage/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_storage_summary_endpoint(self):
        """Storage summary returns authoritatively calculated used_bytes without limits."""
        self.client.force_authenticate(user=self.user)
        MediaFile.objects.create(
            academy_uuid=self.academy.id,
            original_filename="a.png",
            size_bytes=1000,
            storage_key="a.png"
        )
        MediaFile.objects.create(
            academy_uuid=self.academy.id,
            original_filename="b.png",
            size_bytes=2000,
            storage_key="b.png"
        )

        response = self.client.get('/api/v1/storage/usage/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json().get('data', {})
        self.assertEqual(data.get('used_bytes'), 3000)
        self.assertEqual(data.get('used_display'), '2.9 KB')

    def test_upload_and_delete_metering_event_ledger(self):
        """Upload and Delete operations generate immutable StorageUsageEvents with correct deltas."""
        dummy_file = SimpleUploadedFile("video.mp4", b"0" * 5000, content_type="video/mp4")
        media = StorageService.upload_media_direct(
            academy_uuid=self.academy.id,
            user_uuid=self.user.id,
            file_obj=dummy_file,
            original_filename="video.mp4",
            mime_type="video/mp4",
            file_size_bytes=5000
        )

        upload_ev = StorageUsageEvent.objects.filter(media_file=media, event_type=UsageEventType.UPLOAD).first()
        self.assertIsNotNone(upload_ev)
        self.assertEqual(upload_ev.delta_bytes, 5000)
        self.assertEqual(upload_ev.storage_after_bytes, 5000)

        StorageService.delete_media_file(media, hard_delete=False)

        delete_ev = StorageUsageEvent.objects.filter(academy_uuid=self.academy.id, event_type=UsageEventType.DELETE).first()
        self.assertIsNotNone(delete_ev)
        self.assertEqual(delete_ev.delta_bytes, -5000)
        self.assertEqual(delete_ev.storage_after_bytes, 0)

        # Deleting physical file retains historical event
        self.assertEqual(upload_ev.original_filename_snapshot, "video.mp4")

    def test_time_weighted_byte_seconds_calculation(self):
        """Verify time-weighted byte-seconds calculation for upload and deletion within time window."""
        now = timezone.now()
        t0 = now - timedelta(hours=10)
        t1 = t0 + timedelta(hours=2) # Upload 100MB
        t2 = t1 + timedelta(hours=4) # Delete 100MB

        # Create upload event at t1
        StorageUsageEvent.objects.create(
            academy_uuid=self.academy.id,
            event_type=UsageEventType.UPLOAD,
            delta_bytes=100000000,
            storage_before_bytes=0,
            storage_after_bytes=100000000,
            file_size_bytes=100000000,
            occurred_at=t1
        )

        # Create delete event at t2
        StorageUsageEvent.objects.create(
            academy_uuid=self.academy.id,
            event_type=UsageEventType.DELETE,
            delta_bytes=-100000000,
            storage_before_bytes=100000000,
            storage_after_bytes=0,
            file_size_bytes=100000000,
            occurred_at=t2
        )

        calc = StorageMeteringService.calculate_byte_seconds_between(self.academy.id, t0, now)

        # Expected: 100MB * 4 hours (14400 seconds) = 1,440,000,000,000 byte-seconds
        expected_byte_seconds = 100000000 * 14400
        self.assertEqual(calc['byte_seconds'], expected_byte_seconds)
        self.assertEqual(calc['peak_bytes'], 100000000)

    def test_monthly_billing_and_credit_deduction(self):
        """Verify closing monthly billing period and deducting credits through CreditService."""
        billing = StorageBillingService.close_billing_period(self.academy.id, year=2026, month=8)
        self.assertIsNotNone(billing)
        self.assertEqual(billing.billing_period, "2026-08")

        # Charge billing period
        charged = StorageBillingService.charge_billing_period(billing)
        self.assertEqual(charged.status, BillingStatus.CHARGED)

        # Idempotency check: Charging again should return same record without extra debit
        charged_again = StorageBillingService.charge_billing_period(charged)
        self.assertEqual(charged_again.status, BillingStatus.CHARGED)

    def test_insufficient_credits_handling(self):
        """Academy with 0 balance attempting to charge storage billing sets status INSUFFICIENT_CREDITS."""
        account = CreditService.get_or_create_account(self.academy_b)
        account.balance = Decimal('0.000000')
        account.save()

        # Create 1 GB storage event for Academy B
        now = timezone.now()
        StorageUsageEvent.objects.create(
            academy_uuid=self.academy_b.id,
            event_type=UsageEventType.UPLOAD,
            delta_bytes=1073741824,
            storage_before_bytes=0,
            storage_after_bytes=1073741824,
            file_size_bytes=1073741824,
            occurred_at=now - timedelta(days=15)
        )

        billing = StorageBillingService.close_billing_period(self.academy_b.id, year=2026, month=8)
        charged = StorageBillingService.charge_billing_period(billing)
        self.assertEqual(charged.status, BillingStatus.INSUFFICIENT_CREDITS)

    def test_pre_upload_estimate_normal_file(self):
        """Verify pre-upload cost calculation for ordinary files (PDF, images)."""
        from storage.estimate import StorageEstimateService
        res = StorageEstimateService.calculate_pre_upload_estimate(
            filename="document.pdf",
            file_size_bytes=25 * 1024 * 1024,
            mime_type="application/pdf",
            academy_uuid=self.academy.id
        )
        self.assertFalse(res["is_video"])
        self.assertEqual(res["estimated_source_bytes"], 25 * 1024 * 1024)
        self.assertEqual(res["estimated_streaming_bytes"], 0)
        self.assertGreater(Decimal(res["estimated_monthly_credits"]), Decimal('0.0000'))

    def test_pre_upload_estimate_video_file_caps_ladder(self):
        """Verify video pre-upload estimate caps quality ladder at source height (360p source produces <=360p)."""
        from storage.estimate import StorageEstimateService
        res = StorageEstimateService.calculate_pre_upload_estimate(
            filename="lesson-360p.mp4",
            file_size_bytes=50 * 1024 * 1024,
            mime_type="video/mp4",
            academy_uuid=self.academy.id,
            duration_seconds=300.0,
            width=640,
            height=360
        )
        self.assertTrue(res["is_video"])
        self.assertIn("360p", res["planned_qualities"])
        self.assertNotIn("1080p", res["planned_qualities"])
        self.assertNotIn("720p", res["planned_qualities"])
        self.assertGreater(res["estimated_streaming_bytes"], 0)

    def test_video_transcoder_hls_generation(self):
        """Verify VideoTranscoder process_media_video creates master.m3u8 and records STREAMING_GENERATED storage event."""
        import tempfile
        from storage.models import MediaFile, ProcessingStatus, UsageEventType, StorageUsageEvent
        from storage.transcoder import VideoTranscoder, get_ffmpeg_binary

        # Create real sample source video file on disk
        source_dir = os.path.join(settings.MEDIA_ROOT, f"academies/{self.academy.id}/videos/test_vid")
        os.makedirs(source_dir, exist_ok=True)
        source_path = os.path.join(source_dir, "original.mp4")
        ffmpeg_bin = get_ffmpeg_binary()
        if ffmpeg_bin and os.path.isfile(ffmpeg_bin):
            subprocess.run([
                ffmpeg_bin, '-y', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=320x240:rate=1',
                '-c:v', 'libx264', source_path
            ], capture_output=True, check=True)
        else:
            with open(source_path, "wb") as f:
                f.write(b"DUMMY_MP4_SOURCE_VIDEO_BYTES_TEST")

        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            original_filename="test_lesson.mp4",
            stored_filename="original.mp4",
            storage_key=f"academies/{self.academy.id}/videos/test_vid/original.mp4",
            relative_path=f"academies/{self.academy.id}/videos/test_vid/original.mp4",
            mime_type="video/mp4",
            size_bytes=len(b"DUMMY_MP4_SOURCE_VIDEO_BYTES_TEST"),
            media_type="VIDEO",
            status="ACTIVE",
            processing_status=ProcessingStatus.QUEUED,
            storage_path=source_path
        )

        res_file = VideoTranscoder.process_media_video(media_file.id)
        self.assertEqual(res_file.processing_status, ProcessingStatus.READY)
        self.assertTrue(res_file.stream_manifest_key.endswith("master.m3u8"))
        self.assertGreater(res_file.streaming_size_bytes, 0)
        self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, res_file.stream_manifest_key)))

        # Check STREAMING_GENERATED event recorded
        evt = StorageUsageEvent.objects.filter(media_file_uuid_snapshot=media_file.id, event_type=UsageEventType.STREAMING_GENERATED).first()
        self.assertIsNotNone(evt)
        self.assertGreater(evt.delta_bytes, 0)

    def test_invalid_segment_validation(self):
        """Verify validate_hls_segment rejects non-MPEG-TS synthetic files."""
        from storage.transcoder import VideoTranscoder
        fake_seg = os.path.join(settings.MEDIA_ROOT, "fake_segment.ts")
        with open(fake_seg, "wb") as f:
            f.write(b"NOT_REAL_MPEG_TS_SYNTHETIC_BYTES")

        try:
            with self.assertRaises(RuntimeError):
                VideoTranscoder.validate_hls_segment(fake_seg)
        finally:
            if os.path.exists(fake_seg):
                os.remove(fake_seg)

    def test_ffmpeg_failure_handling(self):
        """Verify FFmpeg failure marks MediaFile status as FAILED."""
        from unittest.mock import patch
        from storage.models import MediaFile, ProcessingStatus
        from storage.transcoder import VideoTranscoder

        source_dir = os.path.join(settings.MEDIA_ROOT, f"academies/{self.academy.id}/videos/fail_vid")
        os.makedirs(source_dir, exist_ok=True)
        source_path = os.path.join(source_dir, "original.mp4")
        with open(source_path, "wb") as f:
            f.write(b"CORRUPT_BYTES")

        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            original_filename="fail.mp4",
            stored_filename="original.mp4",
            storage_key=f"academies/{self.academy.id}/videos/fail_vid/original.mp4",
            relative_path=f"academies/{self.academy.id}/videos/fail_vid/original.mp4",
            mime_type="video/mp4",
            size_bytes=13,
            media_type="VIDEO",
            status="ACTIVE",
            processing_status=ProcessingStatus.QUEUED,
            storage_path=source_path
        )

        res_file = VideoTranscoder.process_media_video(media_file.id)
        self.assertEqual(res_file.processing_status, ProcessingStatus.FAILED)
        self.assertTrue(len(res_file.processing_error) > 0)

    def test_storage_rental_tracking_upload_delete(self):
        """Verify upload increases used_bytes by file size and delete decreases it safely."""
        from storage.models import AcademyStorageUsage
        from credits.services import StorageBillingService as CreditStorageBillingService

        ten_mb = 10 * 1024 * 1024
        usage_obj = CreditStorageBillingService.increment_storage(self.academy, ten_mb)
        self.assertEqual(usage_obj.used_bytes, ten_mb)

        usage_obj = CreditStorageBillingService.decrement_storage(self.academy, ten_mb)
        self.assertEqual(usage_obj.used_bytes, 0)

        # Ensure no negative used_bytes on repeated delete
        usage_obj = CreditStorageBillingService.decrement_storage(self.academy, ten_mb)
        self.assertEqual(usage_obj.used_bytes, 0)

    def test_interval_billing_calculation_and_idempotency(self):
        """Verify interval billing calculation: 10 GB, Rate 2 credits/GB -> 20 Credits charged idempotently."""
        from storage.models import StorageBillingSettings, StorageUsageCharge, AcademyStorageUsage
        from storage.tasks import capture_and_bill_due_storage_usage
        from credits.services import StorageBillingService as CreditStorageBillingService, CreditService

        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.storage_credit_rate_per_gb = Decimal("2.0000")
        settings_obj.storage_billing_interval = "6_HOURS"
        settings_obj.save()

        # Set usage to 10 GB
        ten_gb = 10 * (1024 ** 3)
        CreditStorageBillingService.increment_storage(self.academy, ten_gb)

        bal_before = CreditService.get_balance(self.academy)

        # Execute task 3 times
        capture_and_bill_due_storage_usage()
        capture_and_bill_due_storage_usage()
        capture_and_bill_due_storage_usage()

        charges = StorageUsageCharge.objects.filter(academy=self.academy)
        self.assertEqual(charges.count(), 1)

        charge = charges.first()
        self.assertIn(charge.status, ["SUCCESS", "CHARGED"])
        self.assertIsNotNone(charge.debited_at)
        self.assertIsNotNone(charge.ledger_entry)
        self.assertEqual(charge.used_bytes, ten_gb)
        self.assertEqual(charge.rate_per_gb, Decimal("2.0000"))
        self.assertEqual(charge.charged_credits, Decimal("20.0000"))

        bal_after = CreditService.get_balance(self.academy)
        self.assertEqual(bal_before - bal_after, Decimal("20.000000"))

    def test_rate_snapshot_immutability(self):
        """Verify rate changes in settings do not alter historical StorageUsageCharge rates."""
        from storage.models import StorageBillingSettings, StorageUsageCharge
        from storage.tasks import capture_and_bill_due_storage_usage
        from credits.services import StorageBillingService as CreditStorageBillingService

        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.storage_credit_rate_per_gb = Decimal("2.0000")
        settings_obj.storage_billing_interval = "12_HOURS"
        settings_obj.save()

        ten_gb = 10 * (1024 ** 3)
        CreditStorageBillingService.increment_storage(self.academy, ten_gb)

        capture_and_bill_due_storage_usage()

        charge = StorageUsageCharge.objects.filter(academy=self.academy).first()
        self.assertEqual(charge.rate_per_gb, Decimal("2.0000"))
        self.assertEqual(charge.charged_credits, Decimal("20.0000"))

        # Update global rate to 3 credits / GB
        settings_obj.storage_credit_rate_per_gb = Decimal("3.0000")
        settings_obj.save()

        # Re-fetch charge: historical snapshotted values must remain unchanged
        charge.refresh_from_db()
        self.assertEqual(charge.rate_per_gb, Decimal("2.0000"))

    def test_storage_metering_accumulation_and_single_debit_at_debit_time(self):
        from decimal import Decimal
        from storage.models import StorageBillingSettings, StorageBillingCycle
        from storage.tasks import meter_due_storage_usage, debit_due_storage_billing_cycles
        from credits.services import StorageBillingService as CreditStorageBillingService, CreditService

        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.storage_credit_rate_per_gb = Decimal("2.0000")
        settings_obj.storage_billing_interval = "10_SECONDS"
        settings_obj.save()

        five_gb = 5 * (1024 ** 3)
        CreditStorageBillingService.increment_storage(self.academy, five_gb)

        bal_before = CreditService.get_balance(self.academy)

        # 1. Metering run: usage accumulates into OPEN cycle, balance unchanged
        meter_due_storage_usage()
        bal_after_meter = CreditService.get_balance(self.academy)
        self.assertEqual(bal_before, bal_after_meter)

        open_cycle = StorageBillingCycle.objects.filter(academy=self.academy, status="OPEN").first()
        self.assertIsNotNone(open_cycle)
        self.assertEqual(open_cycle.meter_records.count(), 1)
        self.assertEqual(open_cycle.accumulated_credits, Decimal("10.0000"))

        # 2. Debit run: balance deducted exactly once for accumulated total
        debit_due_storage_billing_cycles(force_debit=True)

        bal_after_debit = CreditService.get_balance(self.academy)
        self.assertEqual(bal_before - bal_after_debit, Decimal("10.000000"))

        open_cycle.refresh_from_db()
        self.assertIn(open_cycle.status, ["SETTLED", "DEBITED"])
        self.assertIsNotNone(open_cycle.settled_at or open_cycle.debited_at)

    def test_file_lifetime_billing_two_days_only(self):
        """PATH 26: A file present for 2 days appears in applicable meter records, disappears after delete, but past records remain."""
        from decimal import Decimal
        from datetime import timedelta
        from django.utils import timezone
        from storage.models import StorageBillingSettings, StorageBillingCycle, StorageMeterRecord, AcademyStorageUsage
        from storage.tasks import meter_due_storage_usage
        from credits.services import StorageBillingService as CreditStorageBillingService

        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.storage_credit_rate_per_gb = Decimal("2.0000")
        settings_obj.storage_billing_interval = "10_SECONDS"
        settings_obj.save()

        two_gb = 2 * (1024 ** 3)
        CreditStorageBillingService.increment_storage(self.academy, two_gb)

        usage = AcademyStorageUsage.objects.get(academy=self.academy)

        # Interval 1
        meter_due_storage_usage()

        # Reset last_billed_at to trigger Interval 2
        AcademyStorageUsage.objects.filter(academy=self.academy).update(last_billed_at=timezone.now() - timedelta(seconds=15))
        meter_due_storage_usage()

        # Delete file
        CreditStorageBillingService.decrement_storage(self.academy, two_gb)

        # Reset last_billed_at to trigger Interval 3
        AcademyStorageUsage.objects.filter(academy=self.academy).update(last_billed_at=timezone.now() - timedelta(seconds=15))
        meter_due_storage_usage()

        # Reset last_billed_at to trigger Interval 4
        AcademyStorageUsage.objects.filter(academy=self.academy).update(last_billed_at=timezone.now() - timedelta(seconds=15))
        meter_due_storage_usage()

        records = StorageMeterRecord.objects.filter(academy=self.academy).order_by('created_at')
        self.assertEqual(records.count(), 4)

        # First 2 records metered 2 GB
        self.assertEqual(records[0].used_bytes, two_gb)
        self.assertEqual(records[1].used_bytes, two_gb)

        # Last 2 records metered 0 GB
        self.assertEqual(records[2].used_bytes, 0)
        self.assertEqual(records[3].used_bytes, 0)

        open_cycle = StorageBillingCycle.objects.filter(academy=self.academy, status="OPEN").first()
        self.assertEqual(open_cycle.accumulated_credits, Decimal("8.0000"))

    def test_upload_safety_and_billing_non_blocking(self):
        """Verify upload creates storage usage row automatically, increments once, works with billing ON/OFF, and doesn't debit credits."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from storage.services import StorageService
        from storage.models import AcademyStorageUsage, StorageBillingSettings
        from credits.services import CreditService

        # Ensure no prior AcademyStorageUsage row exists for self.academy
        AcademyStorageUsage.objects.filter(academy=self.academy).delete()

        # Turn billing ON
        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.save()

        bal_before = CreditService.get_balance(self.academy)

        dummy_file = SimpleUploadedFile("sample_doc.pdf", b"pdf document content binary data 123", content_type="application/pdf")
        media = StorageService.upload_media_direct(
            academy_uuid=self.academy.id,
            user_uuid=self.user.id,
            file_obj=dummy_file,
            original_filename="sample_doc.pdf",
            mime_type="application/pdf",
            file_size_bytes=len(dummy_file.read())
        )

        self.assertIsNotNone(media)

        # Check AcademyStorageUsage row auto-created
        usage = AcademyStorageUsage.objects.get(academy=self.academy)
        self.assertEqual(usage.file_count, 1)
        self.assertGreater(usage.used_bytes, 0)

        # Check balance was NOT debited during upload
        bal_after = CreditService.get_balance(self.academy)
        self.assertEqual(bal_before, bal_after)

    def test_celery_beat_schedule_consolidation(self):
        """Verify CELERY_BEAT_SCHEDULE contains both storage tasks and existing platform tasks without overwriting."""
        from django.conf import settings
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertIn('meter-due-storage-usage', schedule)
        self.assertIn('debit-due-storage-billing-cycles', schedule)
        self.assertIn('dispatch-pending-email-jobs-every-minute', schedule)
        self.assertEqual(schedule['meter-due-storage-usage']['task'], 'storage.meter_due_storage_usage')
        self.assertEqual(schedule['debit-due-storage-billing-cycles']['task'], 'storage.debit_due_storage_billing_cycles')

    def test_ten_seconds_metering_accumulates_without_settling(self):
        """Verify 10_SECONDS metering interval creates meter records and accumulates credits into OPEN cycle without debiting balance."""
        from decimal import Decimal
        from storage.models import StorageBillingSettings, StorageBillingCycle, StorageMeterRecord, AcademyStorageUsage
        from storage.tasks import meter_due_storage_usage, debit_due_storage_billing_cycles
        from credits.services import CreditService, StorageBillingService as CreditStorageBillingService

        # Setup billing settings
        settings_obj = StorageBillingSettings.get_settings()
        settings_obj.storage_billing_enabled = True
        settings_obj.storage_credit_rate_per_gb = Decimal("50000.0000")
        settings_obj.storage_billing_interval = "10_SECONDS"
        settings_obj.save()

        # Add initial storage
        one_gb = 1024 ** 3
        CreditStorageBillingService.increment_storage(self.academy, one_gb)

        bal_initial = CreditService.get_balance(self.academy)

        # Run meter task
        meter_due_storage_usage()

        # Run debit task (not forced) -> should NOT trigger settlement
        debit_due_storage_billing_cycles(force_debit=False)

        open_cycle = StorageBillingCycle.objects.get(academy=self.academy, status="OPEN")
        self.assertEqual(open_cycle.meter_records.count(), 1)
        self.assertGreater(open_cycle.accumulated_credits, Decimal("0.0000"))

        # Verify Academy balance remained unchanged
        bal_after_meter = CreditService.get_balance(self.academy)
        self.assertEqual(bal_initial, bal_after_meter)


class HLSVideoUploadArchitectureTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from academy.models import Academy
        from users_roles.models import User, SystemRoleCode
        from control_panel.models import SystemSetting

        self.client = APIClient()
        self.academy = Academy.objects.create(name="HLS Test Academy", slug="hls-test-academy", email="hls@test.com", hls_video_enabled=True)
        self.user = User.objects.create_user(
            email="hlsuploader@test.com",
            password="Password123!",
            full_name="HLS Uploader",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy,
            is_email_verified=True,
            password_setup_completed=True
        )
        self.client.force_authenticate(user=self.user)
        SystemSetting.objects.update_or_create(key='hls_streaming_enabled', defaults={'value': 'true'})

    def test_image_upload_hls_disabled(self):
        """Verify image upload results in direct processing mode and READY status without enqueuing Celery task."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        img_file = SimpleUploadedFile("avatar.png", b"PNG dummy data 123", content_type="image/png")
        with patch("storage.tasks.process_video_transcoding_task.delay") as mock_delay:
            resp = self.client.post("/api/v1/storage/upload/", {"file": img_file}, format="multipart")
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            self.assertEqual(data["processing_mode"], "direct")
            self.assertEqual(data["processing_status"], "READY")
            self.assertEqual(data["processing_progress"], 100)
            mock_delay.assert_not_called()

    def test_video_upload_hls_off(self):
        """Verify video upload with hls_enabled=false results in direct processing mode and READY status."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        vid_file = SimpleUploadedFile("sample.mp4", b"MP4 dummy video content", content_type="video/mp4")
        with patch("storage.tasks.process_video_transcoding_task.delay") as mock_delay:
            resp = self.client.post(
                "/api/v1/storage/upload/",
                {"file": vid_file, "hls_enabled": "false", "adaptive_streaming_enabled": "false"},
                format="multipart"
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            self.assertEqual(data["processing_mode"], "direct")
            self.assertEqual(data["processing_status"], "READY")
            self.assertEqual(data["processing_progress"], 100)
            self.assertFalse(data["adaptive_streaming_enabled"])
            mock_delay.assert_not_called()

    def test_video_upload_hls_on(self):
        """Verify video upload with hls_enabled=true results in HLS mode and QUEUED status, enqueuing Celery task once."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        vid_file = SimpleUploadedFile("sample_hls.mp4", b"MP4 dummy video content for HLS", content_type="video/mp4")
        with patch("storage.tasks.process_video_transcoding_task.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    "/api/v1/storage/upload/",
                    {"file": vid_file, "hls_enabled": "true", "adaptive_streaming_enabled": "true"},
                    format="multipart"
                )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            self.assertEqual(data["processing_mode"], "hls")
            self.assertEqual(data["processing_status"], "QUEUED")
            self.assertEqual(data["processing_progress"], 5)
            self.assertTrue(data["adaptive_streaming_enabled"])
            mock_delay.assert_called_once_with(data["id"])

    def test_global_hls_off_takes_precedence(self):
        """Verify global SystemSetting hls_streaming_enabled=false overrides request hls_enabled=true."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from control_panel.models import SystemSetting
        from unittest.mock import patch

        SystemSetting.objects.update_or_create(key='hls_streaming_enabled', defaults={'value': 'false'})

        vid_file = SimpleUploadedFile("sample.mp4", b"MP4 dummy content", content_type="video/mp4")
        with patch("storage.tasks.process_video_transcoding_task.delay") as mock_delay:
            resp = self.client.post(
                "/api/v1/storage/upload/",
                {"file": vid_file, "hls_enabled": "true"},
                format="multipart"
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            self.assertEqual(data["processing_mode"], "direct")
            self.assertEqual(data["processing_status"], "READY")
            mock_delay.assert_not_called()

    def test_academy_hls_off_takes_precedence(self):
        """Verify Academy hls_video_enabled=false forces direct mode when request does not override."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        self.academy.hls_video_enabled = False
        self.academy.save()

        vid_file = SimpleUploadedFile("sample.mp4", b"MP4 dummy content", content_type="video/mp4")
        with patch("storage.tasks.process_video_transcoding_task.delay") as mock_delay:
            resp = self.client.post(
                "/api/v1/storage/upload/",
                {"file": vid_file},
                format="multipart"
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            self.assertEqual(data["processing_mode"], "direct")
            self.assertEqual(data["processing_status"], "READY")
            mock_delay.assert_not_called()

    def test_boolean_flag_parsing(self):
        """Verify parse_bool correctly parses various string representations of boolean flags."""
        from storage.utils import parse_bool
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("1"))
        self.assertTrue(parse_bool("yes"))
        self.assertTrue(parse_bool("on"))
        self.assertTrue(parse_bool(True))

        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("0"))
        self.assertFalse(parse_bool("no"))
        self.assertFalse(parse_bool("off"))
        self.assertFalse(parse_bool(False))

        self.assertFalse(parse_bool(None, default=False))
        self.assertTrue(parse_bool(None, default=True))

    def test_invalid_course_uuid_400(self):
        """Verify uploading with invalid course_uuid format returns HTTP 400 INVALID_UUID."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        doc_file = SimpleUploadedFile("doc.pdf", b"pdf bytes", content_type="application/pdf")
        resp = self.client.post("/api/v1/storage/upload/", {"file": doc_file, "course_uuid": "not-a-uuid"}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_UUID")

    def test_nonexistent_course_uuid_404(self):
        """Verify uploading with random course_uuid returns HTTP 404 COURSE_NOT_FOUND."""
        import uuid
        from django.core.files.uploadedfile import SimpleUploadedFile
        doc_file = SimpleUploadedFile("doc.pdf", b"pdf bytes", content_type="application/pdf")
        resp = self.client.post("/api/v1/storage/upload/", {"file": doc_file, "course_uuid": str(uuid.uuid4())}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.json()["error"]["code"], "COURSE_NOT_FOUND")

    def test_invalid_lesson_uuid_400(self):
        """Verify uploading with invalid lesson_uuid format returns HTTP 400 INVALID_UUID."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        doc_file = SimpleUploadedFile("doc.pdf", b"pdf bytes", content_type="application/pdf")
        resp = self.client.post("/api/v1/storage/upload/", {"file": doc_file, "lesson_uuid": "malformed-lesson-id"}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_UUID")

    def test_nonexistent_lesson_uuid_404(self):
        """Verify uploading with non-existent lesson_uuid returns HTTP 404 LESSON_NOT_FOUND."""
        import uuid
        from django.core.files.uploadedfile import SimpleUploadedFile
        doc_file = SimpleUploadedFile("doc.pdf", b"pdf bytes", content_type="application/pdf")
        resp = self.client.post("/api/v1/storage/upload/", {"file": doc_file, "lesson_uuid": str(uuid.uuid4())}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.json()["error"]["code"], "LESSON_NOT_FOUND")

    def test_celery_broker_failure_graceful_handling(self):
        """Verify system returns HTTP 201 and sets processing_status=FAILED if Celery broker enqueue fails."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from storage.models import MediaFile, ProcessingStatus
        from unittest.mock import patch

        vid_file = SimpleUploadedFile("broker_fail.mp4", b"MP4 dummy content for broker test", content_type="video/mp4")
        with patch("storage.tasks.process_video_transcoding_task.delay", side_effect=Exception("Redis connection refused")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    "/api/v1/storage/upload/",
                    {"file": vid_file, "hls_enabled": "true"},
                    format="multipart"
                )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            data = resp.json()["data"]
            media_id = data["id"]

            media_obj = MediaFile.objects.get(id=media_id)
            self.assertEqual(media_obj.processing_status, ProcessingStatus.FAILED)
            self.assertEqual(media_obj.processing_progress, 0)
            self.assertIn("temporarily unavailable", media_obj.processing_error)

    def test_storage_metering_recorded_exactly_once(self):
        """Verify single upload creates exactly one StorageUsageEvent with UPLOAD type."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from storage.models import StorageUsageEvent, UsageEventType, MediaFile

        doc_file = SimpleUploadedFile("single_meter.pdf", b"test content for single metering", content_type="application/pdf")
        initial_event_count = StorageUsageEvent.objects.filter(academy_uuid=self.academy.id, event_type=UsageEventType.UPLOAD).count()

        resp = self.client.post("/api/v1/storage/upload/", {"file": doc_file}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        final_event_count = StorageUsageEvent.objects.filter(academy_uuid=self.academy.id, event_type=UsageEventType.UPLOAD).count()
        self.assertEqual(final_event_count, initial_event_count + 1)

    def test_serializer_for_queued_media(self):
        """Verify MediaFileSerializer for QUEUED media safely returns empty stream_url and empty renditions list."""
        from storage.models import MediaFile, ProcessingMode, ProcessingStatus
        from storage.serializers import MediaFileSerializer

        media = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.user.id,
            original_filename="queued_test.mp4",
            stored_filename="queued_test.mp4",
            storage_key="test/queued_test.mp4",
            mime_type="video/mp4",
            size_bytes=1000,
            media_type="VIDEO",
            processing_mode=ProcessingMode.HLS,
            processing_status=ProcessingStatus.QUEUED,
            processing_progress=5,
            stream_manifest_key=""
        )

        data = MediaFileSerializer(media).data
        self.assertEqual(data["stream_url"], "")
        self.assertEqual(data["renditions"], [])
        self.assertEqual(data["processing_status"], "QUEUED")



