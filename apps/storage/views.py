#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import action
from storage.models import MediaFile, UploadSession, StorageUsageRollup, StorageMonthlyBilling
from storage.services import StorageService
from storage.serializers import (
    MediaFileSerializer, UploadUrlRequestSerializer, DirectUploadSerializer,
    UpdateMediaFileSerializer, StorageAccountSummarySerializer, StorageUsageRollupSerializer
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
        filename = request.data.get('filename') or request.data.get('original_filename') or 'uploaded_file'
        size_bytes = int(request.data.get('file_size_bytes') or request.data.get('size_bytes') or 0)
        mime_type = request.data.get('mime_type') or request.data.get('content_type') or ''

        duration_seconds = request.data.get('duration_seconds')
        if duration_seconds is not None:
            duration_seconds = float(duration_seconds)

        width = request.data.get('width')
        if width is not None:
            width = int(width)

        height = request.data.get('height')
        if height is not None:
            height = int(height)

        adaptive_streaming_enabled = str(request.data.get('adaptive_streaming_enabled', 'true')).lower() in ('true', '1')

        acad_uuid = request.user.academy.id if (hasattr(request.user, 'academy') and request.user.academy) else None

        from storage.estimate import StorageEstimateService
        estimate_data = StorageEstimateService.calculate_pre_upload_estimate(
            filename=filename,
            file_size_bytes=size_bytes,
            mime_type=mime_type,
            academy_uuid=acad_uuid,
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            adaptive_streaming_enabled=adaptive_streaming_enabled
        )

        return api_response(data=estimate_data)

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

        adaptive_streaming_enabled = str(request.data.get('adaptive_streaming_enabled', 'true')).lower() in ('true', '1')

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

        media_file.adaptive_streaming_enabled = adaptive_streaming_enabled
        media_file.save(update_fields=['adaptive_streaming_enabled'])

        # Trigger background HLS video transcoding ONLY if file is VIDEO and adaptive streaming is ON
        if (media_file.media_type == 'VIDEO' or (uploaded_file.content_type and uploaded_file.content_type.startswith('video/'))) and adaptive_streaming_enabled:
            from storage.models import ProcessingStatus
            from storage.tasks import process_video_transcoding_task

            media_file.processing_status = ProcessingStatus.QUEUED
            media_file.processing_progress = 5
            media_file.save(update_fields=['processing_status', 'processing_progress'])

            media_id = str(media_file.id)
            def queue_transcoding():
                try:
                    process_video_transcoding_task.delay(media_id)
                except Exception as exc:
                    logger.warning(f"Could not enqueue Celery video task for media {media_id}; asset remains QUEUED in DB: {exc}")

            transaction.on_commit(queue_transcoding)
        elif media_file.media_type == 'VIDEO' and not adaptive_streaming_enabled:
            from storage.models import ProcessingStatus
            media_file.processing_status = ProcessingStatus.READY
            media_file.processing_progress = 100
            media_file.save(update_fields=['processing_status', 'processing_progress'])

        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Media uploaded successfully and registered in storage engine.",
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
        qs = MediaFile.objects.filter(academy_uuid=acad_uuid).exclude(status='DELETED')

        # 1. Search Filter
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            from django.db.models import Q
            qs = qs.filter(
                Q(original_filename__icontains=search_query) |
                Q(display_name__icontains=search_query) |
                Q(stored_filename__icontains=search_query)
            )

        # 2. Media Type Category Filter
        media_type = self.request.query_params.get('media_type', '').upper().strip()
        if media_type and media_type != 'ALL':
            if media_type == 'IMAGES': media_type = 'IMAGE'
            elif media_type == 'VIDEOS': media_type = 'VIDEO'
            elif media_type == 'DOCUMENTS': media_type = 'DOCUMENT'
            qs = qs.filter(media_type=media_type)

        # 3. Unused Only Filter
        unused_only = self.request.query_params.get('unused_only', 'false').lower() in ('true', '1')
        if unused_only:
            from storage.selectors import MediaUsageSelector
            all_ids = list(qs.values_list('id', flat=True))
            used_ids = set()
            for mf in qs:
                if MediaUsageSelector.get_usage(mf).get('is_used', False):
                    used_ids.add(mf.id)
            unused_ids = [fid for fid in all_ids if fid not in used_ids]
            qs = qs.filter(id__in=unused_ids)

        # 4. Server-side Ordering
        ordering = self.request.query_params.get('ordering', '-created_at').strip()
        allowed_ordering = ['created_at', '-created_at', 'original_filename', '-original_filename', 'size_bytes', '-size_bytes']
        if ordering in allowed_ordering:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-created_at')

        return qs

    def update(self, request, *args, **kwargs):
        media_file = self.get_object()
        serializer = UpdateMediaFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = request.FILES.get('file')
        updated_media = StorageService.update_media_file(
            media_file=media_file,
            file_obj=uploaded_file,
            original_filename=serializer.validated_data.get('original_filename'),
            display_name=serializer.validated_data.get('display_name'),
            mime_type=serializer.validated_data.get('mime_type')
        )

        return api_response(
            data=MediaFileSerializer(updated_media).data,
            message="Media updated successfully."
        )

    @action(detail=True, methods=['get'], url_path='usage')
    def usage(self, request, pk=None):
        media_file = self.get_object()
        from storage.selectors import MediaUsageSelector
        usage_data = MediaUsageSelector.get_usage(media_file)
        return api_response(data=usage_data)

    @action(detail=True, methods=['post'], url_path='retry-processing')
    def retry_processing(self, request, pk=None):
        media_file = self.get_object()
        if media_file.media_type != 'VIDEO':
            raise CubixSkillAPIException("Only video media assets can be processed into HLS adaptive streams.", code="NOT_VIDEO")

        from storage.models import ProcessingStatus
        from storage.tasks import process_video_transcoding_task

        media_file.processing_status = ProcessingStatus.QUEUED
        media_file.processing_error = ''
        media_file.processing_progress = 5
        media_file.save(update_fields=['processing_status', 'processing_error', 'processing_progress'])

        media_id = str(media_file.id)
        def queue_retry_transcoding():
            try:
                process_video_transcoding_task.delay(media_id)
            except Exception as exc:
                logger.warning(f"Could not enqueue Celery video retry task for media {media_id}: {exc}")

        transaction.on_commit(queue_retry_transcoding)

        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Video processing retry queued successfully."
        )

    def destroy(self, request, *args, **kwargs):
        media_file = self.get_object()
        force = request.query_params.get('force', 'false').lower() in ('true', '1')
        hard_delete = request.query_params.get('hard', 'false').lower() in ('true', '1')

        from storage.selectors import MediaUsageSelector
        usage_data = MediaUsageSelector.get_usage(media_file)
        usage_count = usage_data.get('usage_count', 0)

        if usage_count > 0 and not force:
            raise CubixSkillAPIException(
                f"Media asset '{media_file.display_name or media_file.original_filename}' is currently in use across {usage_count} location(s). Confirm deletion to remove reference.",
                code="MEDIA_IN_USE",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        StorageService.delete_media_file(media_file, hard_delete=hard_delete)
        return api_response(message="Media file safely deleted from storage and database.")

#--------------------------------------------------------------
# Storage Usage & History View
#--------------------------------------------------------------

class StorageUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'academy') or not request.user.academy:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")

        acad_uuid = request.user.academy.id
        from storage.selectors import StorageSummarySelector
        from storage.utils import format_bytes

        summary = StorageSummarySelector.get_summary(acad_uuid)
        summary['used_display'] = format_bytes(summary['used_bytes'])

        return api_response(data=summary)


class StorageCurrentPeriodView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'academy') or not request.user.academy:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")

        acad_uuid = request.user.academy.id
        from storage.metering import StorageBillingService, StorageMeteringService
        from storage.utils import format_bytes

        account = StorageMeteringService.get_or_create_account(acad_uuid)
        current_record = StorageBillingService.close_billing_period(acad_uuid)

        from decimal import Decimal
        bytes_in_gb = Decimal('1073741824')
        gb_hours = (Decimal(str(current_record.total_byte_seconds)) / (bytes_in_gb * Decimal('3600'))).quantize(Decimal('0.0001'))
        gb_days = (Decimal(str(current_record.total_byte_seconds)) / (bytes_in_gb * Decimal('86400'))).quantize(Decimal('0.0001'))

        return api_response(data={
            "used_bytes": account.current_usage_bytes,
            "used_display": format_bytes(account.current_usage_bytes),
            "billing_period": current_record.billing_period,
            "billing_period_start": current_record.billing_period_start,
            "billing_period_end": current_record.billing_period_end,
            "byte_seconds": current_record.total_byte_seconds,
            "gb_hours": str(gb_hours),
            "gb_days": str(gb_days),
            "gb_month": str(current_record.billable_units_gb_month),
            "estimated_credits": str(current_record.credits_calculated),
            "rate_snapshot": current_record.rate_snapshot
        })


class StorageDailyRollupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'academy') or not request.user.academy:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")

        acad_uuid = request.user.academy.id
        from storage.metering import StorageBillingService
        from storage.models import StorageUsageRollup
        from storage.serializers import StorageUsageRollupSerializer

        # Ensure today's rollup is built
        StorageBillingService.build_daily_rollup(acad_uuid)

        rollups = StorageUsageRollup.objects.filter(academy_uuid=acad_uuid, interval_type='DAILY').order_by('-period_start')[:30]
        return api_response(data=StorageUsageRollupSerializer(rollups, many=True).data)


class StorageMonthlyBillingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'academy') or not request.user.academy:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")

        acad_uuid = request.user.academy.id
        from storage.metering import StorageBillingService
        from storage.models import StorageMonthlyBilling
        from storage.serializers import StorageMonthlyBillingSerializer

        # Ensure current month record exists
        StorageBillingService.close_billing_period(acad_uuid)

        billings = StorageMonthlyBilling.objects.filter(academy_uuid=acad_uuid).order_by('-billing_period_start')
        return api_response(data=StorageMonthlyBillingSerializer(billings, many=True).data)

