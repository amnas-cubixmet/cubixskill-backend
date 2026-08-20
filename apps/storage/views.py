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

        acad_uuid = request.user.academy.id if request.user.academy else None
        user_uuid = request.user.id if request.user else None

        res = StorageService.create_upload_session(
            academy_uuid=acad_uuid,
            user_uuid=user_uuid,
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
# Pre-Upload Cost Estimation View
#--------------------------------------------------------------

class EstimateUploadCostView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        size_bytes = int(request.data.get('size_bytes', 0))
        category = request.data.get('category', 'GENERAL')

        acad_uuid = request.user.academy.id if (hasattr(request.user, 'academy') and request.user.academy) else None
        account = StorageService.get_or_create_account(acad_uuid)

        from control_panel.models import StorageBillingConfig
        config = StorageBillingConfig.objects.first()
        if not config:
            config = StorageBillingConfig.objects.create()

        price_per_unit = float(config.price_per_unit)
        unit = config.storage_unit.upper()

        if unit == 'MB':
            unit_bytes = 1024 * 1024
        elif unit == 'TB':
            unit_bytes = 1024 * 1024 * 1024 * 1024
        else:
            unit_bytes = 1024 * 1024 * 1024

        additional_units = size_bytes / unit_bytes
        estimated_additional_cost = round(additional_units * price_per_unit, 2)

        curr_bytes = account.current_usage_bytes
        new_bytes = curr_bytes + size_bytes

        curr_gb = round(curr_bytes / (1024 * 1024 * 1024), 2)
        new_gb = round(new_bytes / (1024 * 1024 * 1024), 2)
        file_mb = round(size_bytes / (1024 * 1024), 2)

        return api_response(
            data={
                "file_size_bytes": size_bytes,
                "file_size_display": f"{file_mb} MB" if file_mb < 1024 else f"{round(file_mb / 1024, 2)} GB",
                "price_per_unit": price_per_unit,
                "storage_unit": unit,
                "additional_monthly_cost": estimated_additional_cost,
                "current_storage_usage": f"{curr_gb} GB",
                "estimated_new_usage": f"{new_gb} GB",
                "currency": "INR",
                "category": category
            }
        )

#--------------------------------------------------------------
# Direct Upload View
#--------------------------------------------------------------

class DirectUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            raise CubixSkillAPIException("No file provided.", code="NO_FILE", status_code=400)

        acad_uuid = request.user.academy.id if (hasattr(request.user, 'academy') and request.user.academy) else None
        user_uuid = request.user.id if request.user else None

        media_file = StorageService.upload_media_direct(
            academy_uuid=acad_uuid,
            user_uuid=user_uuid,
            file_obj=uploaded_file,
            original_filename=uploaded_file.name,
            mime_type=uploaded_file.content_type or 'application/octet-stream',
            file_size_bytes=uploaded_file.size
        )

        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Media uploaded successfully and metadata saved to media database.",
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
# Confirm Upload View
#--------------------------------------------------------------

class ConfirmUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, upload_id):
        acad_uuid = request.user.academy.id if request.user.academy else None
        try:
            session = UploadSession.objects.get(id=upload_id, academy_uuid=acad_uuid)
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
        acad_uuid = self.request.user.academy.id if self.request.user.academy else None
        return MediaFile.objects.filter(academy_uuid=acad_uuid).exclude(status='DELETED')

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

        acad_uuid = request.user.academy.id if request.user.academy else None
        account = StorageService.get_or_create_account(acad_uuid)
        snapshots = StorageUsageSnapshot.objects.filter(academy_uuid=acad_uuid)[:10]

        return api_response(
            data={
                "account": StorageAccountSummarySerializer(account).data,
                "recent_snapshots": StorageSnapshotSerializer(snapshots, many=True).data
            }
        )
