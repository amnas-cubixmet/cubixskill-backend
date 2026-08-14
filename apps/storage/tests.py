#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from unittest.mock import patch, MagicMock
from django.test import TestCase
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from academy.models import Academy
from users_roles.models import User, SystemRoleCode
from storage.models import MediaFile, MediaStatus, MediaType, AcademyStorageAccount
from storage.services import StorageService

#--------------------------------------------------------------
# Storage Service Unit & API Tests
#--------------------------------------------------------------

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

    @patch('storage.services.storage_client')
    def test_direct_media_upload_service(self, mock_storage_client):
        """Verify uploading file to MinIO/S3 and recording MediaFile in PostgreSQL."""
        mock_storage_client.upload_file.return_value = "academies/1/media/test.pdf"
        dummy_file = SimpleUploadedFile("test_document.pdf", b"PDF dummy content", content_type="application/pdf")

        media_file = StorageService.upload_media_direct(
            academy=self.academy,
            user=self.user,
            file_obj=dummy_file,
            original_filename="test_document.pdf",
            mime_type="application/pdf",
            file_size_bytes=len(b"PDF dummy content")
        )

        self.assertEqual(media_file.academy, self.academy)
        self.assertEqual(media_file.media_type, MediaType.DOCUMENT)
        self.assertEqual(media_file.status, MediaStatus.ACTIVE)
        mock_storage_client.upload_file.assert_called_once()

        # Verify storage accounting updated in PostgreSQL
        account = AcademyStorageAccount.objects.get(academy=self.academy)
        self.assertEqual(account.current_usage_bytes, media_file.size_bytes)

    @patch('storage.services.storage_client')
    def test_delete_media_file_deletes_from_minio_and_postgres(self, mock_storage_client):
        """Verify deleting media file cleans up MinIO storage object and updates PostgreSQL."""
        mock_storage_client.upload_file.return_value = "academies/1/media/test.png"
        mock_storage_client.delete_file.return_value = True

        dummy_image = SimpleUploadedFile("avatar.png", b"PNG dummy bytes", content_type="image/png")
        media_file = StorageService.upload_media_direct(
            academy=self.academy,
            user=self.user,
            file_obj=dummy_image,
            original_filename="avatar.png",
            mime_type="image/png",
            file_size_bytes=len(b"PNG dummy bytes")
        )

        StorageService.delete_media_file(media_file, hard_delete=False)

        mock_storage_client.delete_file.assert_called_with(media_file.storage_key)
        media_file.refresh_from_db()
        self.assertEqual(media_file.status, MediaStatus.DELETED)

        # Verify usage updated in PostgreSQL
        account = AcademyStorageAccount.objects.get(academy=self.academy)
        self.assertEqual(account.current_usage_bytes, 0)
