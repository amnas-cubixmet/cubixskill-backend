#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import action
from storage.models import MediaFile, UploadSession, StorageUsageSnapshot
from storage.services import StorageService
from storage.serializers import (
    MediaFileSerializer, UploadUrlRequestSerializer, DirectUploadSerializer,
    UpdateMediaFileSerializer, StorageAccountSummarySerializer, StorageSnapshotSerializer
)
from core.permissions import CanAccessAcademyPermission
from core.utils import api_response, CubixSkillAPIException

#--------------------------------------------------------------
# Pre-Signed Upload Request View
#--------------------------------------------------------------

class RequestUploadUrlView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = UploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not request.user.academy:
            raise CubixSkillAPIException("User has no associated academy.", code="NO_ACADEMY")

        res = StorageService.create_upload_session(
            academy=request.user.academy,
            user=request.user,
            original_name=data['file_name'],
            mime_type=data['mime_type'],
            file_size_bytes=data['file_size_bytes'],
            purpose=data.get('purpose', 'GENERAL')
        )

        return api_response(
            data={
                "upload_id": res["session"].id,
                "upload_url": res["upload_url"],
                "storage_key": res["storage_key"],
                "expires_in": res["expires_in"]
            },
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
# Direct Upload View
#--------------------------------------------------------------

class DirectUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        if not request.user.academy:
            raise CubixSkillAPIException("User has no associated academy.", code="NO_ACADEMY")

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            raise CubixSkillAPIException("No file provided.", code="NO_FILE", status_code=400)

        media_file = StorageService.upload_media_direct(
            academy=request.user.academy,
            user=request.user,
            file_obj=uploaded_file,
            original_filename=uploaded_file.name,
            mime_type=uploaded_file.content_type or 'application/octet-stream',
            file_size_bytes=uploaded_file.size
        )

        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Media uploaded successfully to MinIO and metadata saved to PostgreSQL.",
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
# Confirm Upload View
#--------------------------------------------------------------

class ConfirmUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, upload_id):
        try:
            session = UploadSession.objects.get(id=upload_id, academy=request.user.academy)
        except UploadSession.DoesNotExist:
            raise CubixSkillAPIException("Upload session not found.", code="NOT_FOUND", status_code=404)

        media_file = StorageService.confirm_upload(session)
        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Upload confirmed and media registered."
        )

#--------------------------------------------------------------
# MediaFile ViewSet
#--------------------------------------------------------------

class MediaFileViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = MediaFileSerializer
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        return MediaFile.objects.filter(academy=self.request.user.academy).exclude(status='DELETED')

    def update(self, request, *args, **kwargs):
        media_file = self.get_object()
        serializer = UpdateMediaFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = request.FILES.get('file')
        updated_media = StorageService.update_media_file(
            media_file=media_file,
            file_obj=uploaded_file,
            original_filename=serializer.validated_data.get('original_filename'),
            mime_type=serializer.validated_data.get('mime_type')
        )

        return api_response(
            data=MediaFileSerializer(updated_media).data,
            message="Media updated successfully in MinIO and PostgreSQL."
        )

    def destroy(self, request, *args, **kwargs):
        media_file = self.get_object()
        hard_delete = request.query_params.get('hard', 'false').lower() in ('true', '1')
        StorageService.delete_media_file(media_file, hard_delete=hard_delete)
        return api_response(message="Media file safely deleted from MinIO storage and PostgreSQL.")

#--------------------------------------------------------------
# Storage Usage & History View
#--------------------------------------------------------------

class StorageUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.academy:
            raise CubixSkillAPIException("No academy linked.", code="NO_ACADEMY")

        account = StorageService.get_or_create_account(request.user.academy)
        snapshots = StorageUsageSnapshot.objects.filter(academy=request.user.academy)[:10]

        return api_response(
            data={
                "account": StorageAccountSummarySerializer(account).data,
                "recent_snapshots": StorageSnapshotSerializer(snapshots, many=True).data
            }
        )
