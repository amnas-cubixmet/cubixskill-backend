"""Regression tests for storage pricing security and real metering."""
from datetime import timedelta
from decimal import Decimal

from academy.models import Academy
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from storage.models import (
    AcademyStorageUsage, MediaFile, MediaStatus,
    StorageBillingCycle, StorageBillingSettings, StorageMeterRecord,
    StorageMeterFileSnapshot,
)
from storage.tasks import meter_due_storage_usage
from users_roles.models import SystemRoleCode, User


class StorageSettingsSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="platform-storage@example.test", password="SecureStoragePassword123!",
            full_name="Platform Storage Admin", role_code=SystemRoleCode.SUPER_ADMIN,
            is_email_verified=True, password_setup_completed=True,
        )
        self.academy = Academy.objects.create(
            name="Storage Academy", slug="storage-settings-academy",
            email="storage@example.test",
        )
        self.instructor = User.objects.create_user(
            email="instructor-storage@example.test", password="SecureStoragePassword123!",
            full_name="Instructor", role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy, is_email_verified=True,
            password_setup_completed=True,
        )
        self.url = "/api/v1/storage/control-panel/settings/"
        self.client.force_authenticate(user=self.admin)

    def test_string_false_disables_billing(self):
        result = self.client.post(self.url, {
            "storage_billing_enabled": "false",
            "storage_billing_interval": "6_HOURS",
            "storage_credit_rate_per_gb": "5.2500",
        }, format="json")
        self.assertEqual(result.status_code, 200)
        policy = StorageBillingSettings.get_settings()
        self.assertFalse(policy.storage_billing_enabled)
        self.assertEqual(policy.storage_credit_rate_per_gb, Decimal("5.2500"))

    def test_rejects_negative_rate_without_changing_saved_price(self):
        policy = StorageBillingSettings.get_settings()
        original = policy.storage_credit_rate_per_gb
        result = self.client.post(self.url, {
            "storage_credit_rate_per_gb": "-25.0000",
        }, format="json")
        self.assertEqual(result.status_code, 400)
        policy.refresh_from_db()
        self.assertEqual(policy.storage_credit_rate_per_gb, original)

    def test_rejects_unknown_interval_and_invalid_boolean(self):
        self.assertEqual(self.client.post(
            self.url, {"storage_billing_interval": "EVERY_SECOND"}, format="json",
        ).status_code, 400)
        self.assertEqual(self.client.post(
            self.url, {"storage_billing_enabled": "incorrect"}, format="json",
        ).status_code, 400)

    @override_settings(DEBUG=False, STORAGE_ALLOW_10_SECOND_METERING=False)
    def test_production_rejects_10_second_paid_metering(self):
        self.assertEqual(self.client.post(self.url, {
            "storage_billing_enabled": True,
            "storage_billing_interval": "10_SECONDS",
        }, format="json").status_code, 400)

    def test_instructor_cannot_view_or_change_platform_rates(self):
        self.client.force_authenticate(user=self.instructor)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {
            "storage_credit_rate_per_gb": "0.0000",
            "storage_billing_enabled": False,
        }, format="json").status_code, 403)


class MeteredStorageAccuracyTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(
            name="Metered Academy", slug="metered-accuracy-academy",
            email="metered@example.test",
        )
        self.policy = StorageBillingSettings.get_settings()
        self.policy.storage_billing_enabled = True
        self.policy.storage_billing_interval = "10_SECONDS"
        self.policy.storage_credit_rate_per_gb = Decimal("3.0000")
        self.policy.save()
        self.media = MediaFile.objects.create(
            academy_uuid=self.academy.id, original_filename="lecture.mp4",
            mime_type="video/mp4", media_type="VIDEO",
            size_bytes=1024 ** 3, streaming_size_bytes=1024 ** 3,
            status=MediaStatus.ACTIVE,
        )

    def test_active_source_plus_streaming_bytes_then_delete(self):
        result = meter_due_storage_usage()
        self.assertIn("1 academies", result)
        first = StorageMeterRecord.objects.filter(academy=self.academy).first()
        self.assertEqual(first.used_bytes, 2 * (1024 ** 3))
        self.assertEqual(first.calculated_credits, Decimal("6.0000"))
        self.assertEqual(StorageMeterFileSnapshot.objects.filter(meter_record=first).count(), 1)
        # The old usage counter can be stale after a deleted file; never bill its
        # previous high-water mark once the media registry is authoritative.
        self.media.status = MediaStatus.DELETED
        self.media.save(update_fields=["status"])
        AcademyStorageUsage.objects.filter(academy=self.academy).update(
            used_bytes=5 * (1024 ** 3),
            last_billed_at=timezone.now() - timedelta(seconds=15),
        )
        meter_due_storage_usage()
        latest = StorageMeterRecord.objects.filter(academy=self.academy).first()
        self.assertEqual(latest.used_bytes, 0)
        self.assertEqual(latest.calculated_credits, Decimal("0.0000"))
        self.assertEqual(StorageMeterFileSnapshot.objects.filter(meter_record=latest).count(), 0)
        self.assertEqual(StorageMeterRecord.objects.filter(academy=self.academy).count(), 2)
        self.assertEqual(AcademyStorageUsage.objects.get(academy=self.academy).used_bytes, 0)

    def test_running_twice_before_due_time_is_idempotent(self):
        meter_due_storage_usage()
        meter_due_storage_usage()
        self.assertEqual(StorageMeterRecord.objects.filter(academy=self.academy).count(), 1)
        self.assertEqual(
            StorageBillingCycle.objects.get(academy=self.academy, status="OPEN").accumulated_credits,
            Decimal("6.0000"),
        )

    @override_settings(DEBUG=False, STORAGE_ALLOW_10_SECOND_METERING=False)
    def test_forbidden_production_ten_second_schedule_does_not_add_usage(self):
        result = meter_due_storage_usage()
        self.assertEqual(result, "Invalid production storage interval")
        self.assertEqual(StorageMeterRecord.objects.count(), 0)
