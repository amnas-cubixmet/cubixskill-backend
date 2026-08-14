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
    StorageUsageSnapshot, StoragePricingRule, MediaStatus, UploadSessionStatus,
    UsageEventType, MediaType
)
from storage.s3_client import storage_client
from core.utils import CubixSkillAPIException

logger = logging.getLogger(__name__)

#--------------------------------------------------------------
# Storage Service
#--------------------------------------------------------------

class StorageService:
    @staticmethod
    def get_or_create_account(academy) -> AcademyStorageAccount:
        account, _ = AcademyStorageAccount.objects.get_or_create(academy=academy)
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
    def create_upload_session(cls, academy, user, original_name: str, mime_type: str, file_size_bytes: int, purpose: str = 'GENERAL') -> dict:
        """
        Create upload session and generate S3/MinIO presigned upload URL.
        """
        account = cls.get_or_create_account(academy)

        # Validate quota/limit if defined
        if account.storage_limit_bytes and (account.current_usage_bytes + file_size_bytes > account.storage_limit_bytes):
            raise CubixSkillAPIException("Academy storage limit exceeded.", code="STORAGE_LIMIT_EXCEEDED")

        safe_ext = original_name.split('.')[-1] if '.' in original_name else 'bin'
        unique_id = uuid.uuid4().hex
        academy_id = academy.id if academy else 'global'
        storage_key = f"academies/{academy_id}/media/{unique_id}.{safe_ext}"

        session = UploadSession.objects.create(
            academy=academy,
            requested_by=user,
            storage_key=storage_key,
            original_name=original_name,
            mime_type=mime_type,
            expected_size_bytes=file_size_bytes,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        presigned_url = storage_client.generate_presigned_upload_url(
            object_key=storage_key,
            mime_type=mime_type,
            expires_in=900
        )

        return {
            "session": session,
            "upload_url": presigned_url,
            "storage_key": storage_key,
            "expires_in": 900
        }

    @classmethod
    @transaction.atomic
    def upload_media_direct(cls, academy, user, file_obj, original_filename: str, mime_type: str, file_size_bytes: int) -> MediaFile:
        """
        Directly upload binary media content to MinIO/S3 and record metadata in PostgreSQL.
        """
        account = cls.get_or_create_account(academy)
        if account.storage_limit_bytes and (account.current_usage_bytes + file_size_bytes > account.storage_limit_bytes):
            raise CubixSkillAPIException("Academy storage limit exceeded.", code="STORAGE_LIMIT_EXCEEDED")

        safe_ext = original_filename.split('.')[-1] if '.' in original_filename else 'bin'
        unique_id = uuid.uuid4().hex
        academy_id = academy.id if academy else 'global'
        storage_key = f"academies/{academy_id}/media/{unique_id}.{safe_ext}"

        # Upload file binary to MinIO S3 object storage
        storage_client.upload_file(file_obj=file_obj, object_key=storage_key, content_type=mime_type)

        media_type = cls.deduce_media_type(mime_type)

        media_file = MediaFile.objects.create(
            academy=academy,
            uploaded_by=user,
            original_filename=original_filename,
            stored_filename=storage_key.split('/')[-1],
            storage_key=storage_key,
            relative_path=storage_key,
            mime_type=mime_type,
            size_bytes=file_size_bytes,
            media_type=media_type,
            status=MediaStatus.ACTIVE,
            uploaded_at=timezone.now()
        )

        # Update Storage Account usage
        account.current_usage_bytes += media_file.size_bytes
        account.save(update_fields=['current_usage_bytes'])

        # Log Usage Event in PostgreSQL
        StorageUsageEvent.objects.create(
            academy=academy,
            media_file=media_file,
            event_type=UsageEventType.FILE_ADDED,
            delta_bytes=media_file.size_bytes,
            usage_after_bytes=account.current_usage_bytes,
            occurred_at=timezone.now()
        )

        return media_file

    @classmethod
    @transaction.atomic
    def confirm_upload(cls, upload_session: UploadSession) -> MediaFile:
        if upload_session.status == UploadSessionStatus.CONFIRMED:
            return MediaFile.objects.get(storage_key=upload_session.storage_key)

        if timezone.now() > upload_session.expires_at:
            upload_session.status = UploadSessionStatus.EXPIRED
            upload_session.save(update_fields=['status'])
            raise CubixSkillAPIException("Upload session expired.", code="SESSION_EXPIRED")

        media_type = cls.deduce_media_type(upload_session.mime_type)

        media_file = MediaFile.objects.create(
            academy=upload_session.academy,
            uploaded_by=upload_session.requested_by,
            original_filename=upload_session.original_name,
            stored_filename=upload_session.storage_key.split('/')[-1],
            storage_key=upload_session.storage_key,
            relative_path=upload_session.storage_key,
            mime_type=upload_session.mime_type,
            size_bytes=upload_session.expected_size_bytes,
            media_type=media_type,
            status=MediaStatus.ACTIVE,
            uploaded_at=timezone.now()
        )

        upload_session.status = UploadSessionStatus.CONFIRMED
        upload_session.confirmed_at = timezone.now()
        upload_session.save(update_fields=['status', 'confirmed_at'])

        # Update Storage Account
        account = cls.get_or_create_account(upload_session.academy)
        account.current_usage_bytes += media_file.size_bytes
        account.save(update_fields=['current_usage_bytes'])

        # Log Usage Event
        StorageUsageEvent.objects.create(
            academy=upload_session.academy,
            media_file=media_file,
            event_type=UsageEventType.FILE_ADDED,
            delta_bytes=media_file.size_bytes,
            usage_after_bytes=account.current_usage_bytes,
            occurred_at=timezone.now()
        )

        return media_file

    @classmethod
    def get_media_access_url(cls, media_file: MediaFile, expires_in: int = 3600) -> str:
        """
        Generate access URL (presigned download or public URL) for MinIO object.
        """
        if not media_file.storage_key:
            return ""
        return storage_client.generate_presigned_download_url(object_key=media_file.storage_key, expires_in=expires_in)

    @classmethod
    @transaction.atomic
    def update_media_file(cls, media_file: MediaFile, file_obj=None, original_filename: str = None, mime_type: str = None) -> MediaFile:
        """
        Update existing media file: replace MinIO binary if new content provided, and update PostgreSQL metadata.
        """
        old_size = media_file.size_bytes
        new_size = old_size

        if file_obj is not None:
            # Delete old file from MinIO
            if media_file.storage_key:
                storage_client.delete_file(media_file.storage_key)

            # Generate new key or reuse
            if original_filename:
                safe_ext = original_filename.split('.')[-1] if '.' in original_filename else 'bin'
                unique_id = uuid.uuid4().hex
                academy_id = media_file.academy.id if media_file.academy else 'global'
                media_file.storage_key = f"academies/{academy_id}/media/{unique_id}.{safe_ext}"
                media_file.stored_filename = media_file.storage_key.split('/')[-1]
                media_file.relative_path = media_file.storage_key

            effective_mime = mime_type or media_file.mime_type
            storage_client.upload_file(file_obj=file_obj, object_key=media_file.storage_key, content_type=effective_mime)

            if hasattr(file_obj, 'size'):
                new_size = file_obj.size
            elif isinstance(file_obj, (bytes, bytearray)):
                new_size = len(file_obj)

            media_file.size_bytes = new_size

        if original_filename:
            media_file.original_filename = original_filename
        if mime_type:
            media_file.mime_type = mime_type
            media_file.media_type = cls.deduce_media_type(mime_type)

        media_file.save()

        # Update storage usage accounting if size changed
        if media_file.academy and new_size != old_size:
            delta = new_size - old_size
            account = cls.get_or_create_account(media_file.academy)
            account.current_usage_bytes = max(0, account.current_usage_bytes + delta)
            account.save(update_fields=['current_usage_bytes'])

            StorageUsageEvent.objects.create(
                academy=media_file.academy,
                media_file=media_file,
                event_type=UsageEventType.FILE_REPLACED,
                delta_bytes=delta,
                usage_after_bytes=account.current_usage_bytes,
                occurred_at=timezone.now()
            )

        return media_file

    @classmethod
    @transaction.atomic
    def delete_media_file(cls, media_file: MediaFile, hard_delete: bool = False) -> None:
        """
        Safely delete media file from BOTH MinIO object storage and PostgreSQL database.
        """
        if media_file.status == MediaStatus.DELETED and not hard_delete:
            return

        # 1. Safely remove object binary from MinIO storage
        if media_file.storage_key:
            try:
                storage_client.delete_file(media_file.storage_key)
            except Exception as e:
                logger.warning(f"Failed to delete object key {media_file.storage_key} from MinIO: {e}")

        # 2. Update Storage usage account in PostgreSQL
        account = cls.get_or_create_account(media_file.academy) if media_file.academy else None
        if account:
            account.current_usage_bytes = max(0, account.current_usage_bytes - media_file.size_bytes)
            account.save(update_fields=['current_usage_bytes'])

            StorageUsageEvent.objects.create(
                academy=media_file.academy,
                media_file=media_file if not hard_delete else None,
                event_type=UsageEventType.FILE_REMOVED,
                delta_bytes=-media_file.size_bytes,
                usage_after_bytes=account.current_usage_bytes,
                occurred_at=timezone.now()
            )

        # 3. Update PostgreSQL record (soft delete or hard delete)
        if hard_delete:
            media_file.delete()
        else:
            media_file.status = MediaStatus.DELETED
            media_file.deleted_at = timezone.now()
            media_file.save(update_fields=['status', 'deleted_at'])
