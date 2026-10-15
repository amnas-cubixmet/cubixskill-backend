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
    """Accumulate one credit reading per due interval; never debit a wallet here.

    Rate units are explicitly credits per GB *per metering interval*.
    Billing cycles are settled by the separate monthly settlement task.
    """
    from django.conf import settings as django_settings
    from storage.utils import bytes_to_gb, storage_interval_delta
    from storage.models import (
        StorageBillingCycle, StorageBillingCycleStatus, StorageBillingSettings,
        StorageMeterFileSnapshot, StorageMeterRecord, AcademyStorageUsage,
        MediaFile, MediaStatus,
    )

    settings_obj = StorageBillingSettings.get_settings()
    if not settings_obj.storage_billing_enabled:
        return "Storage billing disabled"
    if settings_obj.storage_credit_rate_per_gb < 0:
        logger.error("Storage metering blocked: negative pricing rate")
        return "Invalid storage pricing"
    interval_str = settings_obj.storage_billing_interval
    if interval_str == "10_SECONDS" and not django_settings.STORAGE_ALLOW_10_SECOND_METERING:
        logger.error("Storage metering blocked: 10-second test interval in production")
        return "Invalid production storage interval"

    delta = storage_interval_delta(interval_str)
    rate_per_gb = settings_obj.storage_credit_rate_per_gb
    metered_count = 0

    for academy in Academy.objects.all().iterator():
        try:
            # Lock a single academy's usage row before checking the due time.
            # A concurrent worker must observe the updated last_billed_at and skip.
            with transaction.atomic():
                usage, _ = AcademyStorageUsage.objects.get_or_create(
                    academy=academy,
                    defaults={"academy_uuid": academy.id, "used_bytes": 0, "file_count": 0},
                )
                usage = AcademyStorageUsage.objects.select_for_update().get(pk=usage.pk)
                now = timezone.now()
                if usage.last_billed_at and now < usage.last_billed_at + delta:
                    continue

                # Real, currently active file bytes are authoritative. In
                # particular, do not keep a stale maximum after files are deleted.
                active_files = list(
                    MediaFile.objects.filter(
                        academy_uuid=academy.id, status=MediaStatus.ACTIVE,
                    ).order_by("pk")
                )
                active_bytes = sum(max(0, f.total_storage_bytes) for f in active_files)
                # Older academy usage accounting may represent data not yet
                # migrated to MediaFile. Preserve those records ONLY when the
                # academy has never registered a MediaFile; once media rows
                # exist, current active files override stale usage counters.
                has_media_registry = MediaFile.objects.filter(academy_uuid=academy.id).exists()
                used_bytes = active_bytes if has_media_registry else max(0, usage.used_bytes)
                used_gb = bytes_to_gb(used_bytes)
                calculated_credits = (used_gb * rate_per_gb).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP,
                )
                open_cycle = (
                    StorageBillingCycle.objects.select_for_update()
                    .filter(academy=academy, status=StorageBillingCycleStatus.OPEN)
                    .order_by("-cycle_start_at").first()
                )
                if open_cycle is None:
                    # A unique partial constraint ensures exactly one open cycle
                    # per academy; usage-row locking serializes local schedulers.
                    open_cycle = StorageBillingCycle.objects.create(
                        academy=academy, academy_uuid=academy.id,
                        cycle_start_at=now,
                        accumulated_credits=Decimal("0.0000"),
                        status=StorageBillingCycleStatus.OPEN,
                        idempotency_key=f"storage-cycle:{academy.id}:{now.isoformat()}",
                    )

                meter_rec = StorageMeterRecord.objects.create(
                    academy=academy, academy_uuid=academy.id,
                    billing_cycle=open_cycle, metered_at=now,
                    used_bytes=used_bytes, used_gb=used_gb,
                    credit_rate_per_gb=rate_per_gb,
                    calculated_credits=calculated_credits,
                    metering_interval=interval_str,
                    file_count=len(active_files),
                )
                if active_files:
                    StorageMeterFileSnapshot.objects.bulk_create([
                        StorageMeterFileSnapshot(
                            meter_record=meter_rec,
                            academy=academy, academy_uuid=academy.id,
                            media_file=f, media_file_uuid=f.id,
                            filename_snapshot=f.display_name or f.original_filename,
                            media_type_snapshot=f.media_type,
                            size_bytes_snapshot=max(0, f.total_storage_bytes),
                            uploaded_at_snapshot=f.uploaded_at or f.created_at,
                            storage_key_snapshot=f.storage_key or "",
                        )
                        for f in active_files
                    ])

                open_cycle.accumulated_credits = models.F("accumulated_credits") + calculated_credits
                open_cycle.save(update_fields=["accumulated_credits"])
                usage.used_bytes = used_bytes
                usage.file_count = len(active_files)
                usage.last_billed_at = now
                usage.save(update_fields=["used_bytes", "file_count", "last_billed_at"])
                metered_count += 1
        except Exception:
            logger.exception("Storage metering failed for academy %s", academy.id)

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
