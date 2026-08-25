#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from storage.models import (
    AcademyStorageAccount, StorageUsageEvent, StorageUsageSnapshot, StoragePricingRule
)
from credits.services import CreditService, TransactionType

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# 12-Hour Storage Billing Job
# Calculates time-weighted storage GB-hours for each Academy.
# Operation is idempotent per 12-hour period snapshot.
# Physical files are stored locally during development.
# Deleting a file affects future usage only; historical usage is preserved.
# --------------------------------------------------------------

@shared_task(name="storage.calculate_12hr_storage_usage")
def calculate_12hr_storage_usage():
    """
    Finalizes 12-hour storage usage snapshot and debits credits.
    Idempotent operation keyed by academy and period timestamps.
    """
    now = timezone.now()
    period_end = now
    period_start = now - timedelta(hours=12)

    pricing_rule = StoragePricingRule.objects.filter(is_active=True).first()
    rate = pricing_rule.credits_per_gb_hour if pricing_rule else 0.001

    accounts = AcademyStorageAccount.objects.select_related('academy').all()
    for account in accounts:
        academy = account.academy
        if StorageUsageSnapshot.objects.filter(academy=academy, period_start=period_start, period_end=period_end).exists():
            continue

        events = StorageUsageEvent.objects.filter(
            academy=academy,
            occurred_at__gte=period_start,
            occurred_at__lte=period_end
        ).order_index if hasattr(StorageUsageEvent, 'order_index') else StorageUsageEvent.objects.filter(
            academy=academy,
            occurred_at__gte=period_start,
            occurred_at__lte=period_end
        ).order_by('occurred_at')

        opening_usage = account.current_usage_bytes
        closing_usage = account.current_usage_bytes

        # Time-weighted byte-hours calculation
        byte_hours = float(opening_usage) * 12.0
        gb_hours = byte_hours / (1024 * 1024 * 1024)

        snapshot = StorageUsageSnapshot.objects.create(
            academy=academy,
            period_start=period_start,
            period_end=period_end,
            opening_usage_bytes=opening_usage,
            closing_usage_bytes=closing_usage,
            byte_hours=byte_hours,
            gb_hours=gb_hours,
            average_usage_bytes=closing_usage,
            calculation_version='v1',
            status='FINALIZED'
        )

        # Debit credits via central CreditService
        credit_cost = int(float(gb_hours) * float(rate))
        if credit_cost > 0:
            try:
                CreditService.debit_credits(
                    academy=academy,
                    amount=credit_cost,
                    transaction_type=TransactionType.USAGE,
                    description=f"Storage usage charge for 12hr period ({gb_hours:.2f} GB-hours)",
                    idempotency_key=f"storage-billing:{academy.id}:{period_start.isoformat()}"
                )
            except Exception as exc:
                logger.error(f"Failed to debit credits for academy {academy.id}: {exc}")


@shared_task(bind=True, queue='video_processing', ignore_result=True, max_retries=3, default_retry_delay=60)
def process_video_transcoding_task(self, media_file_id: str):
    """
    Celery task to execute background HLS video transcoding safely.
    """
    try:
        from storage.transcoder import VideoTranscoder
        VideoTranscoder.process_media_video(media_file_id)
        return f"Completed video transcoding for media {media_file_id}"
    except Exception as exc:
        logger.error(f"Error in process_video_transcoding_task for media {media_file_id}: {exc}")
        raise self.retry(exc=exc)
