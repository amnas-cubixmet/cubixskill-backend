import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from academy.models import Academy
from celery import shared_task
from django.db import models, transaction
from django.utils import timezone
from storage.models import (
    AcademyStorageUsage,
    MediaFile,
    MediaStatus,
    StorageBillingCycle,
    StorageBillingCycleStatus,
    StorageBillingSettings,
    StorageMeterRecord,
    StorageUsageCharge,
)
from storage.utils import (
    bytes_to_gb,
    get_storage_debit_datetime,
    storage_interval_delta,
)

logger = logging.getLogger(__name__)


@shared_task(name="storage.process_video_transcoding_task")
def process_video_transcoding_task(media_file_id: str):
    """
    Celery task that delegates real FFmpeg HLS video transcoding to VideoTranscoder.process_media_video.
    Accepts string ID to ensure JSON-serializable arguments across Celery broker queues.
    """
    from storage.transcoder import VideoTranscoder
    logger.info("Celery HLS transcoding task started for media_file_id=%s", media_file_id)
    try:
        return VideoTranscoder.process_media_video(media_file_id)
    except Exception as exc:
        logger.exception("Celery HLS transcoding task failed for media_file_id=%s: %s", media_file_id, exc)
        raise exc


def enqueue_hls_safely(media_id: str):
    """
    Safely enqueues the Celery video transcoding task.
    If the Celery broker is unavailable or fails to queue the task, updates MediaFile status to FAILED
    with an error message instead of causing an unhandled HTTP 500 error in the request thread.
    """
    try:
        process_video_transcoding_task.delay(str(media_id))
        logger.info("HLS Celery task queued media_id=%s", media_id)
    except Exception as exc:
        logger.exception("Unable to enqueue HLS Celery task media_id=%s: %s", media_id, exc)
        from storage.models import MediaFile, ProcessingStatus
        MediaFile.objects.filter(
            id=media_id,
            processing_status=ProcessingStatus.QUEUED,
        ).update(
            processing_status=ProcessingStatus.FAILED,
            processing_progress=0,
            processing_error="Video processing queue is temporarily unavailable.",
        )


@shared_task(name="storage.meter_due_storage_usage")
def meter_due_storage_usage():
    """
    Periodically measures physical storage usage, creates a StorageMeterRecord,
    and atomically accumulates calculated credits into the current OPEN StorageBillingCycle.
    Does NOT debit credit balance directly.
    """
    settings_obj = StorageBillingSettings.get_settings()
    if not settings_obj.storage_billing_enabled:
        logger.info("Storage billing is disabled in settings. Skipping metering.")
        return "Storage billing disabled"

    interval_str = settings_obj.storage_billing_interval
    rate_per_gb = settings_obj.storage_credit_rate_per_gb
    delta = storage_interval_delta(interval_str)
    now = timezone.now()
    metered_count = 0

    academies = Academy.objects.all()
    for academy in academies:
        usage, _ = AcademyStorageUsage.objects.get_or_create(
            academy=academy,
            defaults={'academy_uuid': academy.id, 'used_bytes': 0, 'file_count': 0}
        )

        last_billed = usage.last_billed_at
        if last_billed:
            next_due_at = last_billed + delta
            if now < next_due_at:
                logger.info(
                    "Storage meter skipped academy=%s reason=not_due next_due_at=%s",
                    academy.id,
                    next_due_at,
                )
                continue

        active_files = list(MediaFile.objects.filter(academy_uuid=academy.id, status=MediaStatus.ACTIVE))
        actual_file_bytes = sum((f.total_storage_bytes or f.size_bytes) for f in active_files)
        used_bytes = max(usage.used_bytes, actual_file_bytes)
        used_gb = bytes_to_gb(used_bytes)
        calculated_credits = (used_gb * rate_per_gb).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        logger.info(f"Storage meter start academy={academy.id} used_bytes={used_bytes} rate={rate_per_gb} calculated_credits={calculated_credits}")

        try:
            with transaction.atomic():
                open_cycle = StorageBillingCycle.objects.select_for_update().filter(
                    academy=academy,
                    status=StorageBillingCycleStatus.OPEN
                ).order_by('-cycle_start_at').first()

                if not open_cycle:
                    import uuid
                    idempotency_key = f"storage-cycle:{academy.id}:{now.isoformat()}"
                    if StorageBillingCycle.objects.filter(idempotency_key=idempotency_key).exists():
                        idempotency_key = f"storage-cycle:{academy.id}:{now.isoformat()}:{uuid.uuid4().hex[:6]}"

                    open_cycle = StorageBillingCycle.objects.create(
                        academy=academy,
                        academy_uuid=academy.id,
                        cycle_start_at=now,
                        accumulated_credits=Decimal("0.0000"),
                        status=StorageBillingCycleStatus.OPEN,
                        idempotency_key=idempotency_key
                    )

                meter_rec = StorageMeterRecord.objects.create(
                    academy=academy,
                    academy_uuid=academy.id,
                    billing_cycle=open_cycle,
                    metered_at=now,
                    used_bytes=used_bytes,
                    used_gb=used_gb,
                    credit_rate_per_gb=rate_per_gb,
                    calculated_credits=calculated_credits,
                    metering_interval=interval_str,
                    file_count=len(active_files)
                )

                from storage.models import StorageMeterFileSnapshot
                snapshots = [
                    StorageMeterFileSnapshot(
                        meter_record=meter_rec,
                        academy=academy,
                        academy_uuid=academy.id,
                        media_file=f,
                        media_file_uuid=f.id,
                        filename_snapshot=f.display_name or f.original_filename,
                        media_type_snapshot=f.media_type,
                        size_bytes_snapshot=f.total_storage_bytes or f.size_bytes,
                        uploaded_at_snapshot=f.uploaded_at or f.created_at,
                        storage_key_snapshot=f.storage_key or ''
                    )
                    for f in active_files
                ]
                if snapshots:
                    StorageMeterFileSnapshot.objects.bulk_create(snapshots)

                open_cycle.accumulated_credits = models.F('accumulated_credits') + calculated_credits
                open_cycle.save(update_fields=['accumulated_credits'])
                open_cycle.refresh_from_db(fields=['accumulated_credits'])

                usage.last_billed_at = now
                usage.save(update_fields=['last_billed_at'])
                metered_count += 1
                logger.info(f"Storage meter created academy={academy.id} meter={meter_rec.id}")

        except Exception as exc:
            logger.exception(f"Error metering storage for academy {academy.id}: {exc}")

    return f"Metered storage for {metered_count} academies"


@shared_task(name="storage.debit_due_storage_billing_cycles")
def debit_due_storage_billing_cycles(force_debit=False):
    """
    Checks whether the configured Credit Settlement Day + Credit Settlement Time has arrived.
    Executes ONE monthly storage credit settlement using StorageSettlementService.settle_cycle.
    """
    settings_obj = StorageBillingSettings.get_settings()
    if not settings_obj.storage_billing_enabled:
        return "Storage billing disabled"

    now_tz = timezone.localtime()
    day = settings_obj.storage_credit_debit_day or 1
    debit_time = settings_obj.storage_credit_debit_time or datetime.time(0, 0)
    tz = timezone.get_current_timezone()

    debit_count = 0
    academies = Academy.objects.all()

    for academy in academies:
        open_cycle = StorageBillingCycle.objects.filter(
            academy=academy,
            status=StorageBillingCycleStatus.OPEN
        ).order_by('-cycle_start_at').first()

        if not open_cycle:
            continue

        is_due = False
        if force_debit:
            if open_cycle.accumulated_credits <= 0 and StorageUsageCharge.objects.filter(academy=academy).exists():
                continue
            is_due = True
        else:
            scheduled_due = get_storage_debit_datetime(now_tz.year, now_tz.month, day, debit_time, tz)
            is_due = (now_tz >= scheduled_due and open_cycle.cycle_start_at < scheduled_due)

        if not is_due:
            continue

        try:
            from storage.services import StorageSettlementService
            cycle, processed = StorageSettlementService.settle_cycle(open_cycle)
            if processed:
                debit_count += 1
        except Exception as exc:
            logger.exception(f"Error executing storage settlement for academy {academy.id}: {exc}")

    return f"Processed debit for {debit_count} storage billing cycles"


@shared_task(name="storage.capture_and_bill_due_storage_usage")
def capture_and_bill_due_storage_usage():
    """
    Combined runner for metering and debit tasks (manual and test invocation).
    """
    res1 = meter_due_storage_usage()
    res2 = debit_due_storage_billing_cycles(force_debit=True)
    return f"{res1}; {res2}"
