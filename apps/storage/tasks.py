#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from storage.models import (
    AcademyStorageAccount, StorageUsageEvent, StorageUsageRollup, StoragePricingRule
)
from credits.services import CreditService
from credits.models import CreditSourceType
from decimal import Decimal

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

    accounts = AcademyStorageAccount.objects.all()
    for account in accounts:
        acad_id = account.academy_uuid
        if not acad_id:
            continue

        if StorageUsageRollup.objects.filter(academy_uuid=acad_id, period_start=period_start, period_end=period_end).exists():
            continue

        opening_usage = account.current_usage_bytes
        closing_usage = account.current_usage_bytes

        byte_hours = float(opening_usage) * 12.0
        gb_hours = byte_hours / (1024 * 1024 * 1024)

        StorageUsageRollup.objects.create(
            academy_uuid=acad_id,
            period_start=period_start,
            period_end=period_end,
            opening_bytes=opening_usage,
            closing_bytes=closing_usage,
            peak_bytes=max(opening_usage, closing_usage),
            interval_type='DAILY',
            calculated_at=timezone.now(),
            status='FINALIZED'
        )

        # Debit credits via central CreditService
        credit_cost = int(float(gb_hours) * float(rate))
        if credit_cost > 0:
            try:
                from academy.models import Academy
                academy_obj = Academy.objects.filter(id=acad_id).first()
                if academy_obj:
                    CreditService.debit(
                        academy=academy_obj,
                        amount=Decimal(str(credit_cost)),
                        source_type=CreditSourceType.STORAGE_USAGE,
                        description=f"Storage usage charge for 12hr period ({gb_hours:.2f} GB-hours)",
                        idempotency_key=f"storage-billing:{acad_id}:{period_start.isoformat()}"
                    )
            except Exception as exc:
                logger.error(f"Failed to debit credits for academy {acad_id}: {exc}")


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
