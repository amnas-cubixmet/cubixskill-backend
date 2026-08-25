import logging
from decimal import Decimal
from datetime import datetime, time, timezone as dt_timezone
from django.db import transaction
from django.db.models import Sum, Q, Max
from django.utils import timezone
from storage.models import (
    MediaFile, AcademyStorageAccount, StorageUsageEvent, StorageUsageRollup,
    StorageMonthlyBilling, UsageEventType, BillingStatus, MediaStatus
)
from academy.models import Academy
from credits.services import CreditService, CreditPricingService
from credits.models import CreditSourceType, CreditRate
from core.exceptions import CubixSkillAPIException

logger = logging.getLogger(__name__)

BYTES_PER_GB = 1073741824 # 1 GB = 1024^3 bytes

class StorageMeteringService:
    @classmethod
    @transaction.atomic
    def get_or_create_account(cls, academy_uuid) -> AcademyStorageAccount:
        account, _ = AcademyStorageAccount.objects.select_for_update().get_or_create(
            academy_uuid=academy_uuid,
            defaults={'current_usage_bytes': 0, 'billing_enabled': True, 'metering_enabled_at': timezone.now()}
        )
        return account

    @classmethod
    @transaction.atomic
    def record_upload(cls, media_file: MediaFile, user=None, event_type=UsageEventType.UPLOAD, delta_bytes=None) -> StorageUsageEvent:
        """
        Atomically updates Academy storage state and records an immutable UPLOAD or STREAMING_GENERATED event.
        """
        if not media_file.academy_uuid:
            return None

        account = cls.get_or_create_account(media_file.academy_uuid)
        before_bytes = account.current_usage_bytes
        charge_bytes = delta_bytes if delta_bytes is not None else media_file.size_bytes
        after_bytes = before_bytes + charge_bytes

        account.current_usage_bytes = after_bytes
        account.save(update_fields=['current_usage_bytes'])

        event = StorageUsageEvent.objects.create(
            academy_uuid=media_file.academy_uuid,
            media_file=media_file,
            media_file_uuid_snapshot=media_file.id,
            original_filename_snapshot=media_file.original_filename,
            file_type_snapshot=media_file.file_type or media_file.file_extension,
            mime_type_snapshot=media_file.mime_type,
            event_type=event_type,
            delta_bytes=charge_bytes,
            storage_before_bytes=before_bytes,
            storage_after_bytes=after_bytes,
            usage_after_bytes=after_bytes,
            file_size_bytes=charge_bytes,
            occurred_at=timezone.now(),
            performed_by=user,
            source='MEDIA_LIBRARY'
        )

        logger.info(f"Storage UPLOAD event recorded: Academy {media_file.academy_uuid}, +{charge_bytes} bytes")
        return event

    @classmethod
    @transaction.atomic
    def record_delete(cls, media_file: MediaFile, user=None) -> StorageUsageEvent:
        """
        Atomically updates Academy storage state and records an immutable DELETE event.
        """
        if not media_file.academy_uuid:
            return None

        account = cls.get_or_create_account(media_file.academy_uuid)
        before_bytes = account.current_usage_bytes
        after_bytes = max(0, before_bytes - media_file.size_bytes)

        account.current_usage_bytes = after_bytes
        account.save(update_fields=['current_usage_bytes'])

        event = StorageUsageEvent.objects.create(
            academy_uuid=media_file.academy_uuid,
            media_file=media_file,
            media_file_uuid_snapshot=media_file.id,
            original_filename_snapshot=media_file.original_filename,
            file_type_snapshot=media_file.file_type or media_file.file_extension,
            mime_type_snapshot=media_file.mime_type,
            event_type=UsageEventType.DELETE,
            delta_bytes=-media_file.size_bytes,
            storage_before_bytes=before_bytes,
            storage_after_bytes=after_bytes,
            usage_after_bytes=after_bytes,
            file_size_bytes=media_file.size_bytes,
            occurred_at=timezone.now(),
            performed_by=user,
            source='MEDIA_LIBRARY'
        )

        logger.info(f"Storage DELETE event recorded: Academy {media_file.academy_uuid}, -{media_file.size_bytes} bytes")
        return event

    @classmethod
    @transaction.atomic
    def initialize_baseline(cls, academy_uuid, user=None) -> StorageUsageEvent:
        """
        Initializes storage baseline event for pre-existing media files.
        """
        account = cls.get_or_create_account(academy_uuid)
        if StorageUsageEvent.objects.filter(academy_uuid=academy_uuid).exists():
            return None

        active_bytes = MediaFile.objects.filter(
            academy_uuid=academy_uuid
        ).exclude(status=MediaStatus.DELETED).aggregate(s=Sum('size_bytes'))['s'] or 0

        account.current_usage_bytes = active_bytes
        account.metering_enabled_at = timezone.now()
        account.save(update_fields=['current_usage_bytes', 'metering_enabled_at'])

        event = StorageUsageEvent.objects.create(
            academy_uuid=academy_uuid,
            event_type=UsageEventType.BASELINE,
            delta_bytes=active_bytes,
            storage_before_bytes=0,
            storage_after_bytes=active_bytes,
            usage_after_bytes=active_bytes,
            file_size_bytes=active_bytes,
            occurred_at=timezone.now(),
            performed_by=user,
            source='MIGRATION_BASELINE'
        )
        return event

    @classmethod
    def calculate_byte_seconds_between(cls, academy_uuid, start_dt, end_dt) -> dict:
        """
        Integrates storage level over [start_dt, end_dt] to produce exact byte-seconds.
        """
        # Determine opening storage level at start_dt
        prior_event = StorageUsageEvent.objects.filter(
            academy_uuid=academy_uuid,
            occurred_at__lte=start_dt
        ).order_by('-occurred_at', '-id').first()

        current_level = prior_event.storage_after_bytes if prior_event else 0
        opening_bytes = current_level

        events = list(StorageUsageEvent.objects.filter(
            academy_uuid=academy_uuid,
            occurred_at__gte=start_dt,
            occurred_at__lte=end_dt
        ).order_by('occurred_at', 'id'))

        total_byte_seconds = 0
        peak_bytes = current_level
        uploaded_bytes = 0
        deleted_bytes = 0
        upload_count = 0
        delete_count = 0

        last_t = start_dt

        for ev in events:
            if ev.event_type == UsageEventType.UPLOAD:
                uploaded_bytes += ev.file_size_bytes or ev.delta_bytes
                upload_count += 1
            elif ev.event_type == UsageEventType.DELETE:
                deleted_bytes += abs(ev.delta_bytes)
                delete_count += 1

            duration = (ev.occurred_at - last_t).total_seconds()
            if duration > 0:
                total_byte_seconds += current_level * int(duration)

            current_level = ev.storage_after_bytes
            if current_level > peak_bytes:
                peak_bytes = current_level
            last_t = ev.occurred_at

        # Final segment up to end_dt
        final_duration = (end_dt - last_t).total_seconds()
        if final_duration > 0:
            total_byte_seconds += current_level * int(final_duration)

        return {
            'opening_bytes': opening_bytes,
            'closing_bytes': current_level,
            'peak_bytes': peak_bytes,
            'uploaded_bytes': uploaded_bytes,
            'deleted_bytes': deleted_bytes,
            'upload_count': upload_count,
            'delete_count': delete_count,
            'byte_seconds': total_byte_seconds
        }


class StorageBillingService:
    @classmethod
    def get_effective_storage_rate(cls) -> CreditRate:
        """
        Retrieves active STORAGE_MONTHLY CreditRate from Credit Engine.
        """
        return CreditPricingService.get_rate('STORAGE_MONTHLY')

    @classmethod
    @transaction.atomic
    def close_billing_period(cls, academy_uuid, year: int = None, month: int = None) -> StorageMonthlyBilling:
        """
        Calculates exact monthly time-weighted storage usage and creates/updates StorageMonthlyBilling.
        """
        now = timezone.now()
        if not year or not month:
            year = now.year
            month = now.month

        billing_period_str = f"{year:04d}-{month:02d}"

        # Start of month 00:00:00 UTC
        period_start = datetime(year, month, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
        # End of month: 1st of next month 00:00:00 UTC
        if month == 12:
            next_period_start = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
        else:
            next_period_start = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)

        period_end = next_period_start

        # Baseline check
        StorageMeteringService.initialize_baseline(academy_uuid)

        calc = StorageMeteringService.calculate_byte_seconds_between(academy_uuid, period_start, period_end)

        period_seconds = (period_end - period_start).total_seconds()
        if period_seconds <= 0:
            period_seconds = 2592000 # 30 days fallback

        total_byte_sec = Decimal(str(calc['byte_seconds']))
        bytes_in_gb = Decimal(str(BYTES_PER_GB))

        # GB-Month = total_byte_seconds / (1 GB * total seconds in billing month)
        gb_month = (total_byte_sec / (bytes_in_gb * Decimal(str(period_seconds)))).quantize(Decimal('0.000001'))

        rate = cls.get_effective_storage_rate()
        rate_snap = {
            'feature_key': rate.feature_key,
            'name': rate.name,
            'unit_size': str(rate.unit_size),
            'credit_cost': str(rate.credit_cost)
        }

        # Calculate credits: gb_month * credit_cost
        credits_calc = (gb_month * rate.credit_cost).quantize(Decimal('0.000001'))

        is_current_month = (year == now.year and month == now.month)
        init_status = BillingStatus.OPEN if is_current_month else BillingStatus.CALCULATED

        billing_record, _ = StorageMonthlyBilling.objects.update_or_create(
            academy_uuid=academy_uuid,
            billing_period=billing_period_str,
            defaults={
                'billing_period_start': period_start,
                'billing_period_end': period_end,
                'opening_bytes': calc['opening_bytes'],
                'closing_bytes': calc['closing_bytes'],
                'peak_bytes': calc['peak_bytes'],
                'total_uploaded_bytes': calc['uploaded_bytes'],
                'total_deleted_bytes': calc['deleted_bytes'],
                'total_byte_seconds': calc['byte_seconds'],
                'billable_units_gb_month': gb_month,
                'rate_snapshot': rate_snap,
                'credits_calculated': credits_calc,
                'status': init_status,
                'calculated_at': timezone.now()
            }
        )

        return billing_record

    @classmethod
    @transaction.atomic
    def charge_billing_period(cls, billing_record: StorageMonthlyBilling) -> StorageMonthlyBilling:
        """
        Deducts credits for completed StorageMonthlyBilling record idempotently using CreditService.
        """
        if billing_record.status == BillingStatus.CHARGED:
            return billing_record

        if billing_record.credits_calculated <= Decimal('0.000000'):
            billing_record.status = BillingStatus.CHARGED
            billing_record.credits_charged = Decimal('0.000000')
            billing_record.charged_at = timezone.now()
            billing_record.save(update_fields=['status', 'credits_charged', 'charged_at'])
            return billing_record

        try:
            academy = Academy.objects.get(id=billing_record.academy_uuid)
            idempotency_key = f"storage_billing:{billing_record.id}"

            entry = CreditService.debit(
                academy=academy,
                amount=billing_record.credits_calculated,
                source_type=CreditSourceType.STORAGE_USAGE,
                idempotency_key=idempotency_key,
                description=f"Storage billing for {billing_record.billing_period} ({billing_record.billable_units_gb_month} GB-month)",
                reference_type="STORAGE_MONTHLY_BILLING",
                reference_id=str(billing_record.id),
                allow_negative=False
            )

            billing_record.status = BillingStatus.CHARGED
            billing_record.credits_charged = billing_record.credits_calculated
            billing_record.credit_transaction = entry
            billing_record.charged_at = timezone.now()
            billing_record.error_message = ''
            billing_record.save(update_fields=['status', 'credits_charged', 'credit_transaction', 'charged_at', 'error_message'])
            logger.info(f"Charged {billing_record.credits_calculated} Credits for storage billing {billing_record.id}")

        except CubixSkillAPIException as err:
            if getattr(err, 'code', '') == 'INSUFFICIENT_CREDITS' or 'Insufficient credits' in str(err):
                billing_record.status = BillingStatus.INSUFFICIENT_CREDITS
                billing_record.error_message = str(err)
                billing_record.save(update_fields=['status', 'error_message'])
                logger.warning(f"Storage billing {billing_record.id} failed due to INSUFFICIENT_CREDITS: {err}")
            else:
                billing_record.status = BillingStatus.FAILED
                billing_record.error_message = str(err)
                billing_record.save(update_fields=['status', 'error_message'])
                logger.error(f"Storage billing {billing_record.id} failed: {err}")
        except Exception as err:
            billing_record.status = BillingStatus.FAILED
            billing_record.error_message = str(err)
            billing_record.save(update_fields=['status', 'error_message'])
            logger.error(f"Storage billing {billing_record.id} failed unexpectedly: {err}")

        return billing_record

    @classmethod
    def retry_pending_billing(cls, billing_record: StorageMonthlyBilling) -> StorageMonthlyBilling:
        """
        Retries charging a pending or failed StorageMonthlyBilling record.
        """
        return cls.charge_billing_period(billing_record)

    @classmethod
    @transaction.atomic
    def build_daily_rollup(cls, academy_uuid, target_date=None) -> StorageUsageRollup:
        """
        Generates/rebuilds a daily StorageUsageRollup derived record for an Academy.
        """
        if not target_date:
            target_date = timezone.now().date()

        start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=dt_timezone.utc)
        end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=dt_timezone.utc)

        calc = StorageMeteringService.calculate_byte_seconds_between(academy_uuid, start_dt, end_dt)

        rollup, _ = StorageUsageRollup.objects.update_or_create(
            academy_uuid=academy_uuid,
            period_start=start_dt,
            period_end=end_dt,
            interval_type='DAILY',
            defaults={
                'opening_bytes': calc['opening_bytes'],
                'closing_bytes': calc['closing_bytes'],
                'peak_bytes': calc['peak_bytes'],
                'uploaded_bytes': calc['uploaded_bytes'],
                'deleted_bytes': calc['deleted_bytes'],
                'byte_seconds': calc['byte_seconds'],
                'upload_count': calc['upload_count'],
                'delete_count': calc['delete_count'],
                'calculated_at': timezone.now(),
                'status': 'FINALIZED'
            }
        )
        return rollup

    @classmethod
    def reconcile_academy_storage(cls, academy_uuid) -> bool:
        """
        Compares DB MediaFile SUM(size_bytes) against AcademyStorageAccount.current_usage_bytes.
        Emits a RECONCILIATION event if a mismatch is detected.
        """
        account = StorageMeteringService.get_or_create_account(academy_uuid)
        active_bytes = MediaFile.objects.filter(
            academy_uuid=academy_uuid
        ).exclude(status=MediaStatus.DELETED).aggregate(s=Sum('size_bytes'))['s'] or 0

        mismatch = (account.current_usage_bytes != active_bytes)
        if mismatch:
            logger.warning(f"Storage mismatch detected for Academy {academy_uuid}: Account={account.current_usage_bytes}, Actual={active_bytes}")
            before_b = account.current_usage_bytes
            account.current_usage_bytes = active_bytes
            account.last_reconciled_at = timezone.now()
            account.save(update_fields=['current_usage_bytes', 'last_reconciled_at'])

            StorageUsageEvent.objects.create(
                academy_uuid=academy_uuid,
                event_type=UsageEventType.RECONCILIATION,
                delta_bytes=active_bytes - before_b,
                storage_before_bytes=before_b,
                storage_after_bytes=active_bytes,
                usage_after_bytes=active_bytes,
                file_size_bytes=0,
                occurred_at=timezone.now(),
                source='RECONCILIATION_SCAN'
            )

        return mismatch
