import os
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
        from storage.transcoder import VideoTranscoder

        # Create dummy source video file on disk
        source_dir = os.path.join(settings.MEDIA_ROOT, f"academies/{self.academy.id}/videos/test_vid")
        os.makedirs(source_dir, exist_ok=True)
        source_path = os.path.join(source_dir, "original.mp4")
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
