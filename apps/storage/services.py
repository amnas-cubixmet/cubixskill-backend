#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import logging
import uuid
from decimal import Decimal

from core.utils import CubixSkillAPIException
from django.db import transaction
from django.utils import timezone
from storage.models import (
    AcademyStorageAccount,
    MediaFile,
    MediaStatus,
    MediaType,
)

logger = logging.getLogger(__name__)

import os

from django.conf import settings


def determine_media_category(mime_type: str) -> str:
    mime = (mime_type or '').lower()
    if 'font' in mime or 'opentype' in mime or 'truetype' in mime or 'woff' in mime:
        return 'fonts'
    elif 'image' in mime:
        return 'images'
    elif 'video' in mime:
        return 'videos'
    elif 'audio' in mime:
        return 'audio'
    elif 'pdf' in mime or 'document' in mime or 'word' in mime or 'excel' in mime or 'sheet' in mime or 'text' in mime:
        return 'documents'
    return 'other'

def academy_media_upload_path(academy_uuid, mime_type: str, filename: str, course_uuid=None) -> tuple[str, str, str]:
    """
    Returns (storage_key, unique_filename, dest_path)
    storage_key: relative Django media path, e.g. academies/<academy_uuid>/fonts/<uuid>.otf
    """
    acad_str = str(academy_uuid) if academy_uuid else 'global'
    safe_ext = (filename.split('.')[-1] if '.' in filename else 'bin').lower()
    if safe_ext in ['ttf', 'otf', 'woff', 'woff2']:
        category = 'fonts'
    else:
        category = determine_media_category(mime_type)
    unique_filename = f"{uuid.uuid4().hex}.{safe_ext}"
    if course_uuid:
        storage_key = f"academies/{acad_str}/courses/{course_uuid}/{category}/{unique_filename}"
    else:
        storage_key = f"academies/{acad_str}/{category}/{unique_filename}"
    dest_path = os.path.join(settings.MEDIA_ROOT, storage_key)
    return storage_key, unique_filename, dest_path

#--------------------------------------------------------------
# Storage Service
#--------------------------------------------------------------

class StorageService:
    @staticmethod
    def get_or_create_account(academy_uuid) -> AcademyStorageAccount:
        if not academy_uuid:
            academy_uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")
        account, _ = AcademyStorageAccount.objects.get_or_create(academy_uuid=academy_uuid)
        return account

    @classmethod
    def deduce_media_type(cls, mime_type: str) -> str:
        mime = (mime_type or '').lower()
        if 'font' in mime or 'opentype' in mime or 'truetype' in mime or 'woff' in mime:
            return MediaType.FONT
        elif 'image' in mime:
            return MediaType.IMAGE
        elif 'video' in mime:
            return MediaType.VIDEO
        elif 'audio' in mime:
            return MediaType.AUDIO
        elif 'pdf' in mime or 'document' in mime or 'word' in mime or 'excel' in mime or 'sheet' in mime:
            return MediaType.DOCUMENT
        return MediaType.OTHER

    @classmethod
    def upload_media_direct(
        cls,
        academy_uuid,
        user_uuid,
        file_obj,
        original_filename: str,
        mime_type: str,
        file_size_bytes: int,
        course_uuid=None,
        lesson_uuid=None,
        hls_enabled_override=None,
        adaptive_streaming_enabled=True,
    ) -> MediaFile:
        """
        Directly upload binary media content to Django local MEDIA_ROOT folder inside per-Academy/per-Course directory.
        Performs disk write outside DB transaction to eliminate SQLite database lock contention.
        """
        account = cls.get_or_create_account(academy_uuid)

        if account.storage_limit_bytes and (account.current_usage_bytes + file_size_bytes > account.storage_limit_bytes):
            raise CubixSkillAPIException("Academy storage limit exceeded.", code="STORAGE_LIMIT_EXCEEDED")

        storage_key, unique_filename, dest_path = academy_media_upload_path(
            academy_uuid=academy_uuid,
            mime_type=mime_type,
            filename=original_filename,
            course_uuid=course_uuid
        )

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        # Disk write performed outside DB transaction
        with open(dest_path, 'wb') as f:
            if hasattr(file_obj, 'read'):
                file_obj.seek(0)
                f.write(file_obj.read())
            elif isinstance(file_obj, (bytes, bytearray)):
                f.write(file_obj)

        media_type = cls.deduce_media_type(mime_type)
        safe_ext = unique_filename.split('.')[-1]

        from academy.models import Academy
        from control_panel.models import SystemSetting
        from storage.models import ProcessingMode, ProcessingStatus
        from storage.utils import parse_bool

        global_hls = SystemSetting.get_bool('hls_streaming_enabled', default=True)
        academy_obj = None
        if academy_uuid:
            try:
                academy_obj = Academy.objects.filter(id=academy_uuid).first()
            except Exception:
                academy_obj = None

        academy_hls = academy_obj.hls_video_enabled if (academy_obj and hasattr(academy_obj, 'hls_video_enabled')) else True

        if hls_enabled_override is not None:
            upload_hls_choice = parse_bool(hls_enabled_override, default=True)
        else:
            upload_hls_choice = academy_hls

        is_video = (media_type == MediaType.VIDEO or (mime_type and mime_type.lower().startswith('video/')))
        adaptive_flag = parse_bool(adaptive_streaming_enabled, default=True)

        effective_hls = bool(is_video and global_hls and upload_hls_choice and adaptive_flag)

        processing_mode = ProcessingMode.HLS if effective_hls else ProcessingMode.DIRECT
        processing_status = ProcessingStatus.QUEUED if effective_hls else ProcessingStatus.READY
        processing_progress = 5 if effective_hls else 100

        try:
            with transaction.atomic():
                media_file = MediaFile.objects.create(
                    academy_uuid=academy_uuid,
                    uploaded_by_uuid=user_uuid,
                    course_uuid=course_uuid,
                    lesson_uuid=lesson_uuid,
                    original_filename=original_filename,
                    display_name=original_filename,
                    stored_filename=unique_filename,
                    storage_key=storage_key,
                    relative_path=storage_key,
                    mime_type=mime_type,
                    size_bytes=file_size_bytes,
                    file_type=media_type.lower(),
                    file_extension=safe_ext,
                    storage_provider='local',
                    storage_path=dest_path,
                    file_url=f"/media/{storage_key}",
                    media_type=media_type,
                    status=MediaStatus.ACTIVE,
                    adaptive_streaming_enabled=effective_hls,
                    processing_mode=processing_mode,
                    processing_status=processing_status,
                    processing_progress=processing_progress,
                    uploaded_at=timezone.now()
                )

                # Delegate UPLOAD event creation and storage account update to StorageMeteringService
                from storage.metering import StorageMeteringService
                StorageMeteringService.record_upload(media_file)

                return media_file
        except Exception:
            # Clean up disk file if DB transaction fails
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            raise

    @classmethod
    def get_media_access_url(cls, media_file: MediaFile, expires_in: int = 3600) -> str:
        """
        Generate access URL for local media file.
        """
        if not media_file.storage_key:
            return ""
        return f"/media/{media_file.storage_key.lstrip('/')}"

    @classmethod
    @transaction.atomic
    def update_media_file(cls, media_file: MediaFile, file_obj=None, original_filename: str = None, display_name: str = None, mime_type: str = None) -> MediaFile:
        """
        Update existing media file: replace binary if new content provided, and update metadata.
        """
        old_size = media_file.size_bytes
        new_size = old_size

        if file_obj is not None:
            # Delete old local file if present
            if media_file.storage_key:
                old_dest = os.path.join(settings.MEDIA_ROOT, media_file.storage_key)
                if os.path.exists(old_dest):
                    try:
                        os.remove(old_dest)
                    except Exception as e:
                        logger.warning(f"Failed to remove old local media file {old_dest}: {e}")

            effective_mime = mime_type or media_file.mime_type
            effective_filename = original_filename or media_file.original_filename

            storage_key, unique_filename, dest_path = academy_media_upload_path(
                academy_uuid=media_file.academy_uuid,
                mime_type=effective_mime,
                filename=effective_filename
            )

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as f:
                if hasattr(file_obj, 'read'):
                    file_obj.seek(0)
                    f.write(file_obj.read())
                elif isinstance(file_obj, (bytes, bytearray)):
                    f.write(file_obj)

            if hasattr(file_obj, 'size'):
                new_size = file_obj.size
            elif isinstance(file_obj, (bytes, bytearray)):
                new_size = len(file_obj)

            media_file.storage_key = storage_key
            media_file.stored_filename = unique_filename
            media_file.relative_path = storage_key
            media_file.storage_path = dest_path
            media_file.size_bytes = new_size
            media_file.file_url = f"/media/{storage_key}"
            media_file.file_extension = unique_filename.split('.')[-1]

        if original_filename:
            media_file.original_filename = original_filename
            if not display_name:
                media_file.display_name = original_filename
        if display_name:
            media_file.display_name = display_name
        if mime_type:
            media_file.mime_type = mime_type
            media_file.media_type = cls.deduce_media_type(mime_type)
            media_file.file_type = media_file.media_type.lower()

        media_file.save()

        # Record UPLOAD event for updated file size if binary changed
        if media_file.academy_uuid and file_obj is not None:
            from storage.metering import StorageMeteringService
            StorageMeteringService.record_upload(media_file)

        return media_file

    @classmethod
    @transaction.atomic
    def delete_media_file(cls, media_file: MediaFile, hard_delete: bool = False) -> None:
        """
        Safely delete local media file from filesystem and database.
        Database status change and storage metering update are atomic.
        Physical local files are removed safely after transaction commits.
        """
        if media_file.status == MediaStatus.DELETED and not hard_delete:
            return

        # 1. Update database record status atomically
        if hard_delete:
            media_file.delete()
        else:
            # Atomic state transition update
            updated_count = MediaFile.objects.filter(
                id=media_file.id
            ).exclude(status=MediaStatus.DELETED).update(
                status=MediaStatus.DELETED,
                deleted_at=timezone.now()
            )
            if updated_count == 0:
                # Already deleted concurrently
                return
            media_file.refresh_from_db()

        # 2. Delegate DELETE event creation and storage account update to StorageMeteringService
        from storage.metering import StorageMeteringService
        StorageMeteringService.record_delete(media_file)

        # 3. Schedule physical file removal after successful DB commit
        storage_key = media_file.storage_key
        storage_path = media_file.storage_path

        def cleanup_physical_files():
            if storage_key:
                local_path = os.path.join(settings.MEDIA_ROOT, storage_key)
                if os.path.exists(local_path):
                    try:
                        if os.path.isdir(local_path):
                            import shutil
                            shutil.rmtree(local_path)
                        else:
                            os.remove(local_path)
                        logger.info(f"Removed local media file/directory '{local_path}'.")
                    except Exception as e:
                        logger.warning(f"Failed to remove local file '{local_path}': {e}")

            if storage_path:
                dir_path = os.path.dirname(storage_path) if os.path.isfile(storage_path) else storage_path
                if dir_path and os.path.exists(dir_path) and 'videos' in dir_path and dir_path != settings.MEDIA_ROOT:
                    try:
                        import shutil
                        shutil.rmtree(dir_path)
                    except Exception as e:
                        logger.warning(f"Failed to remove derived HLS directory '{dir_path}': {e}")

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(cleanup_physical_files)
        else:
            cleanup_physical_files()

    @classmethod
    def get_media_usage(cls, media_file: MediaFile) -> dict:
        """
        Delegate to MediaUsageSelector.
        """
        from storage.selectors import MediaUsageSelector
        return MediaUsageSelector.get_usage(media_file)

    @classmethod
    def get_storage_usage_summary(cls, academy_uuid) -> dict:
        """
        Delegate to StorageSummarySelector.
        """
        from storage.selectors import StorageSummarySelector
        return StorageSummarySelector.get_summary(academy_uuid)


#--------------------------------------------------------------
# Storage Settlement Service
#--------------------------------------------------------------

class StorageSettlementService:
    @classmethod
    @transaction.atomic
    def settle_cycle(cls, cycle) -> tuple:
        """
        Performs ONE monthly storage credit settlement for the accumulated cycle.
        Debits available credits up to cycle.accumulated_credits.
        Does NOT allow negative credit balance.
        Persists paid_amount, outstanding_amount, and settlement_status (PAID, PARTIALLY_PAID, UNPAID).
        Closes old cycle and opens a new OPEN cycle.
        """
        from credits.models import CreditAccount, CreditSourceType
        from credits.services import CreditService
        from storage.models import (
            StorageBillingCycle,
            StorageBillingCycleStatus,
            StorageSettlementPayment,
            StorageSettlementStatus,
        )

        if cycle.status in [StorageBillingCycleStatus.SETTLED, StorageBillingCycleStatus.DEBITED]:
            return cycle, False

        academy = cycle.academy
        now = timezone.now()

        # Lock credit account and cycle row
        account = CreditAccount.objects.select_for_update().get(id=CreditService.get_or_create_account(academy).id)
        cycle = StorageBillingCycle.objects.select_for_update().get(id=cycle.id)

        if cycle.status in [StorageBillingCycleStatus.SETTLED, StorageBillingCycleStatus.DEBITED]:
            return cycle, False

        original_amount = cycle.accumulated_credits.quantize(Decimal("0.0000"))
        available_credits = max(account.balance, Decimal("0.0000"))
        paid = min(available_credits, original_amount)
        outstanding = original_amount - paid

        ledger_entry = None
        if paid > Decimal("0.0000"):
            start_str = cycle.cycle_start_at.strftime("%d %b %Y")
            end_str = now.strftime("%d %b %Y")
            description = f"Storage usage settlement from {start_str} to {end_str}"
            idempotency_key = f"storage-settlement:{academy.id}:{cycle.id}"

            ledger_entry = CreditService.debit(
                academy=academy,
                amount=paid,
                source_type=CreditSourceType.STORAGE_USAGE,
                idempotency_key=idempotency_key,
                description=description,
                reference_type="StorageBillingCycle",
                reference_id=str(cycle.id),
                allow_negative=False
            )

            StorageSettlementPayment.objects.get_or_create(
                settlement=cycle,
                ledger_entry=ledger_entry,
                defaults={'amount': paid, 'paid_at': now}
            )

        cycle.original_amount = original_amount
        cycle.paid_amount = paid
        cycle.outstanding_amount = outstanding
        cycle.credit_transaction = ledger_entry
        cycle.debited_at = now
        cycle.settled_at = now
        cycle.cycle_end_at = now

        if outstanding == Decimal("0.0000"):
            cycle.settlement_status = StorageSettlementStatus.PAID
        elif paid > Decimal("0.0000"):
            cycle.settlement_status = StorageSettlementStatus.PARTIALLY_PAID
        else:
            cycle.settlement_status = StorageSettlementStatus.UNPAID

        cycle.status = StorageBillingCycleStatus.SETTLED
        cycle.save()

        # Also sync StorageUsageCharge for legacy charge views
        try:
            from storage.models import StorageBillingSettings, StorageUsageCharge
            settings_obj = StorageBillingSettings.get_settings()
            latest_meter = cycle.meter_records.order_by('-metered_at').first()
            last_used_bytes = latest_meter.used_bytes if latest_meter else 0
            StorageUsageCharge.objects.update_or_create(
                idempotency_key=cycle.idempotency_key,
                defaults={
                    'academy': academy,
                    'academy_uuid': academy.id,
                    'billing_started_at': cycle.cycle_start_at,
                    'billing_ended_at': now,
                    'interval': settings_obj.storage_billing_interval,
                    'used_bytes': last_used_bytes,
                    'rate_per_gb': settings_obj.storage_credit_rate_per_gb,
                    'charged_credits': original_amount,
                    'status': 'SUCCESS' if cycle.settlement_status == StorageSettlementStatus.PAID else 'PARTIALLY_PAID',
                    'ledger_entry': ledger_entry
                }
            )
        except Exception as sync_err:
            logger.warning(f"StorageUsageCharge sync failed: {sync_err}")

        # Create new OPEN cycle for future metering records
        new_idempotency_key = f"storage-cycle:{academy.id}:{now.isoformat()}"
        if StorageBillingCycle.objects.filter(idempotency_key=new_idempotency_key).exists():
            new_idempotency_key = f"storage-cycle:{academy.id}:{now.isoformat()}:{uuid.uuid4().hex[:6]}"

        StorageBillingCycle.objects.create(
            academy=academy,
            academy_uuid=academy.id,
            cycle_start_at=now,
            accumulated_credits=Decimal("0.0000"),
            original_amount=Decimal("0.0000"),
            paid_amount=Decimal("0.0000"),
            outstanding_amount=Decimal("0.0000"),
            status=StorageBillingCycleStatus.OPEN,
            idempotency_key=new_idempotency_key
        )

        acad_id_str = str(academy.id)
        current_bal_str = str(account.balance)
        ledger_id_str = str(ledger_entry.id) if ledger_entry else None

        def emit_settlement_event():
            try:
                from asgiref.sync import async_to_sync
                from channels.layers import get_channel_layer
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"academy_events_{acad_id_str}",
                        {
                            "type": "academy_event",
                            "data": {
                                "type": "academy.credit_balance.updated",
                                "academy_id": acad_id_str,
                                "reason": "STORAGE_SETTLEMENT",
                                "balance": current_bal_str,
                                "ledger_entry_id": ledger_id_str,
                                "occurred_at": now.isoformat()
                            }
                        }
                    )
            except Exception as event_err:
                logger.warning(f"Failed to publish academy.credit_balance.updated websocket event: {event_err}")

        transaction.on_commit(emit_settlement_event)

        return cycle, True


class StorageOutstandingService:
    @classmethod
    def get_total_outstanding_credits(cls, academy) -> Decimal:
        """
        Returns SUM(outstanding_amount) for all settlements where outstanding_amount > 0.
        """
        if not academy:
            return Decimal("0.0000")
        from django.db.models import Sum
        from storage.models import StorageBillingCycle
        total = StorageBillingCycle.objects.filter(
            academy=academy,
            outstanding_amount__gt=Decimal("0.0000")
        ).aggregate(total=Sum('outstanding_amount'))['total']
        return (total or Decimal("0.0000")).quantize(Decimal("0.0004"))

    @classmethod
    @transaction.atomic
    def apply_available_credits(cls, academy) -> Decimal:
        """
        Applies newly available credits to settle oldest outstanding storage balances first.
        Records Credit Ledger debits and StorageSettlementPayment entries.
        """
        if not academy:
            return Decimal("0.0000")

        from credits.models import CreditAccount, CreditSourceType
        from credits.services import CreditService
        from storage.models import (
            StorageBillingCycle,
            StorageBillingCycleStatus,
            StorageSettlementPayment,
            StorageSettlementStatus,
        )

        outstanding_cycles = StorageBillingCycle.objects.filter(
            academy=academy,
            outstanding_amount__gt=Decimal("0.0000"),
            status__in=[StorageBillingCycleStatus.SETTLED, StorageBillingCycleStatus.DEBITED]
        ).order_by('settled_at', 'cycle_start_at')

        if not outstanding_cycles.exists():
            return Decimal("0.0000")

        account = CreditAccount.objects.select_for_update().get(id=CreditService.get_or_create_account(academy).id)
        total_paid_now = Decimal("0.0000")
        now = timezone.now()

        for cycle in outstanding_cycles:
            cycle = StorageBillingCycle.objects.select_for_update().get(id=cycle.id)
            available = max(account.balance, Decimal("0.0000"))
            if available <= Decimal("0.0000"):
                break
            if cycle.outstanding_amount <= Decimal("0.0000"):
                continue

            payment_amount = min(available, cycle.outstanding_amount).quantize(Decimal("0.0004"))
            if payment_amount <= Decimal("0.0000"):
                continue

            idempotency_key = f"storage-outstanding-pay:{cycle.id}:{cycle.paid_amount}:{payment_amount}"
            start_str = cycle.cycle_start_at.strftime("%d %b %Y")
            description = f"Paid outstanding storage debt for period from {start_str}"

            ledger_entry = CreditService.debit(
                academy=academy,
                amount=payment_amount,
                source_type=CreditSourceType.STORAGE_USAGE,
                idempotency_key=idempotency_key,
                description=description,
                reference_type="StorageBillingCycle",
                reference_id=str(cycle.id),
                allow_negative=False
            )

            StorageSettlementPayment.objects.create(
                settlement=cycle,
                ledger_entry=ledger_entry,
                amount=payment_amount,
                paid_at=now
            )

            cycle.paid_amount += payment_amount
            cycle.outstanding_amount -= payment_amount
            if cycle.outstanding_amount <= Decimal("0.0000"):
                cycle.outstanding_amount = Decimal("0.0000")
                cycle.settlement_status = StorageSettlementStatus.PAID
            else:
                cycle.settlement_status = StorageSettlementStatus.PARTIALLY_PAID

            cycle.save()
            total_paid_now += payment_amount

            # Refresh account balance for next loop iteration
            account.refresh_from_db(fields=['balance'])

        return total_paid_now

