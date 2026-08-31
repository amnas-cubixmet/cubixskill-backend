#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

import uuid
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from storage.models import (
    MediaFile, UploadSession, AcademyStorageAccount, StorageUsageEvent,
    StorageUsageRollup, StorageMonthlyBilling, StoragePricingRule, MediaStatus, UploadSessionStatus,
    UsageEventType, MediaType
)
from storage.s3_client import storage_client
from core.utils import CubixSkillAPIException

logger = logging.getLogger(__name__)

import os
from django.conf import settings

def determine_media_category(mime_type: str) -> str:
    mime = (mime_type or '').lower()
    if 'image' in mime:
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
    storage_key: relative Django media path, e.g. academies/<academy_uuid>/courses/<course_uuid>/images/<uuid>.jpg
    """
    acad_str = str(academy_uuid) if academy_uuid else 'global'
    category = determine_media_category(mime_type)
    safe_ext = (filename.split('.')[-1] if '.' in filename else 'bin').lower()
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
        if 'image' in mime:
            return MediaType.IMAGE
        elif 'video' in mime:
            return MediaType.VIDEO
        elif 'audio' in mime:
            return MediaType.AUDIO
        elif 'pdf' in mime or 'document' in mime or 'word' in mime or 'excel' in mime or 'sheet' in mime:
            return MediaType.DOCUMENT
        return MediaType.OTHER

    @classmethod
    @transaction.atomic
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
        hls_enabled_override=None
    ) -> MediaFile:
        """
        Directly upload binary media content to Django local MEDIA_ROOT folder inside per-Academy/per-Course directory.
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

        global_hls = SystemSetting.get_bool('hls_streaming_enabled', default=True)
        academy_obj = None
        if academy_uuid:
            try:
                academy_obj = Academy.objects.filter(id=academy_uuid).first()
            except Exception:
                academy_obj = None

        academy_hls = academy_obj.hls_video_enabled if (academy_obj and hasattr(academy_obj, 'hls_video_enabled')) else True

        if hls_enabled_override is not None:
            if isinstance(hls_enabled_override, str):
                upload_hls_choice = hls_enabled_override.lower() in ('true', '1', 'yes', 'on')
            else:
                upload_hls_choice = bool(hls_enabled_override)
        else:
            upload_hls_choice = academy_hls

        effective_hls = global_hls and upload_hls_choice
        is_video = (media_type == MediaType.VIDEO or (mime_type and mime_type.startswith('video/')))

        processing_mode = ProcessingMode.HLS if (is_video and effective_hls) else ProcessingMode.DIRECT
        processing_status = ProcessingStatus.QUEUED if (is_video and effective_hls) else ProcessingStatus.READY

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
            processing_mode=processing_mode,
            processing_status=processing_status,
            processing_progress=5 if (is_video and global_hls) else 100,
            uploaded_at=timezone.now()
        )

        # Delegate UPLOAD event creation and storage account update to StorageMeteringService
        from storage.metering import StorageMeteringService
        StorageMeteringService.record_upload(media_file)

        return media_file

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
        """
        if media_file.status == MediaStatus.DELETED and not hard_delete:
            return

        # 1. Delegate DELETE event creation and storage account update to StorageMeteringService
        from storage.metering import StorageMeteringService
        StorageMeteringService.record_delete(media_file)

        # 2. Safely remove physical local file from MEDIA_ROOT
        if media_file.storage_key:
            local_path = os.path.join(settings.MEDIA_ROOT, media_file.storage_key)
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                    logger.info(f"Removed local media file '{local_path}'.")
                except Exception as e:
                    logger.warning(f"Failed to remove local file '{local_path}': {e}")

        # 3. Update record
        if hard_delete:
            media_file.delete()
        else:
            media_file.status = MediaStatus.DELETED
            media_file.deleted_at = timezone.now()
            media_file.save(update_fields=['status', 'deleted_at'])

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
