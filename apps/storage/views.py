import logging

from core.permissions import CanAccessAcademyPermission
from core.utils import CubixSkillAPIException, api_response
from django.db import transaction
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView
from storage.models import MediaFile, MediaStatus, StorageUsageRollup, UploadSession
from storage.serializers import (
    MediaFileSerializer,
    StorageUsageRollupSerializer,
    UpdateMediaFileSerializer,
    UploadUrlRequestSerializer,
)
from storage.services import StorageService

logger = logging.getLogger(__name__)

def safe_get_user_academy(user):
    if not user or not user.is_authenticated:
        return None
    try:
        return user.academy
    except Exception:
        return None

def safe_get_user_academy_id(user):
    if not user or not user.is_authenticated:
        return None
    acad_id = getattr(user, 'academy_id', None)
    if acad_id:
        return acad_id
    acad = safe_get_user_academy(user)
    return acad.id if acad else None

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
            raise CubixSkillAPIException("File is required.", code="FILE_REQUIRED", status_code=status.HTTP_400_BAD_REQUEST)

        if uploaded_file.size == 0:
            raise CubixSkillAPIException("The uploaded file is empty.", code="EMPTY_FILE", status_code=status.HTTP_400_BAD_REQUEST)

        from django.conf import settings
        mime = (uploaded_file.content_type or '').lower()
        max_size_mb = getattr(settings, 'DOCUMENT_MAX_SIZE_MB', 25)
        if 'image' in mime:
            max_size_mb = getattr(settings, 'IMAGE_MAX_SIZE_MB', 10)
        elif 'video' in mime:
            max_size_mb = getattr(settings, 'VIDEO_MAX_SIZE_MB', 500)
        elif 'audio' in mime:
            max_size_mb = getattr(settings, 'AUDIO_MAX_SIZE_MB', 100)

        max_size_bytes = max_size_mb * 1024 * 1024
        if uploaded_file.size > max_size_bytes:
            raise CubixSkillAPIException(
                f"File size ({uploaded_file.size / (1024 * 1024):.1f} MB) exceeds maximum allowed limit of {max_size_mb} MB.",
                code="FILE_TOO_LARGE",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from storage.utils import parse_bool

        raw_hls = request.data.get('hls_enabled') if 'hls_enabled' in request.data else request.data.get('hls')
        hls_requested = parse_bool(raw_hls, default=True) if raw_hls is not None else None

        raw_adaptive = request.data.get('adaptive_streaming_enabled') if 'adaptive_streaming_enabled' in request.data else request.data.get('adaptive_hls')
        adaptive_streaming_enabled = parse_bool(raw_adaptive, default=True) if raw_adaptive is not None else True

        user_academy = safe_get_user_academy(request.user)
        acad_uuid = safe_get_user_academy_id(request.user)
        user_uuid = getattr(request.user, 'id', None)

        if not acad_uuid and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException(
                "No academy linked to authenticated user.",
                code="NO_ACADEMY",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        raw_course_uuid = request.data.get('course_uuid') or request.data.get('course_id') or request.data.get('course')
        raw_lesson_uuid = request.data.get('lesson_uuid') or request.data.get('lesson_id') or request.data.get('lesson')

        course_uuid = None
        if raw_course_uuid and str(raw_course_uuid).strip():
            import uuid
            try:
                valid_c_uuid = uuid.UUID(str(raw_course_uuid).strip())
            except (ValueError, TypeError):
                raise CubixSkillAPIException("Invalid course UUID format.", code="INVALID_UUID", status_code=status.HTTP_400_BAD_REQUEST)

            from courses.models import Course
            if getattr(request.user, 'role_code', '') in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
                if not Course.objects.filter(id=valid_c_uuid).exists():
                    raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)
            else:
                if not acad_uuid or not Course.objects.filter(id=valid_c_uuid, academy_id=acad_uuid).exists():
                    raise CubixSkillAPIException("Course not found or access denied.", code="COURSE_NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)
            course_uuid = valid_c_uuid

        lesson_uuid = None
        if raw_lesson_uuid and str(raw_lesson_uuid).strip():
            import uuid
            try:
                valid_l_uuid = uuid.UUID(str(raw_lesson_uuid).strip())
            except (ValueError, TypeError):
                raise CubixSkillAPIException("Invalid lesson UUID format.", code="INVALID_UUID", status_code=status.HTTP_400_BAD_REQUEST)

            from lessons.models import Lesson
            lesson_qs = Lesson.objects.filter(id=valid_l_uuid)
            if course_uuid:
                lesson_qs = lesson_qs.filter(module__course_id=course_uuid)
            if getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF'] and acad_uuid:
                lesson_qs = lesson_qs.filter(module__course__academy_id=acad_uuid)

            if not lesson_qs.exists():
                raise CubixSkillAPIException("Lesson not found or access denied.", code="LESSON_NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)
            lesson_uuid = valid_l_uuid

        from storage.models import MediaType, ProcessingMode, ProcessingStatus
        from storage.tasks import enqueue_hls_safely

        from django.db import utils as db_utils

        try:
            media_file = StorageService.upload_media_direct(
                academy_uuid=acad_uuid,
                user_uuid=user_uuid,
                file_obj=uploaded_file,
                original_filename=uploaded_file.name,
                mime_type=uploaded_file.content_type or 'application/octet-stream',
                file_size_bytes=uploaded_file.size,
                course_uuid=course_uuid,
                lesson_uuid=lesson_uuid,
                hls_enabled_override=hls_requested,
                adaptive_streaming_enabled=adaptive_streaming_enabled
            )

            should_queue_hls = (
                media_file.media_type == MediaType.VIDEO
                and media_file.processing_mode == ProcessingMode.HLS
                and media_file.processing_status == ProcessingStatus.QUEUED
            )

            if should_queue_hls:
                media_id = str(media_file.id)
                enqueue_hls_safely(media_id)

            logger.info(
                "Direct upload stored media_id=%s mode=%s status=%s",
                media_file.id,
                media_file.processing_mode,
                media_file.processing_status,
            )
        except CubixSkillAPIException:
            raise
        except db_utils.OperationalError as op_err:
            if 'locked' in str(op_err).lower():
                logger.warning("Storage upload database lock contention: %s", op_err)
                raise CubixSkillAPIException(
                    "Database is currently busy processing concurrent operations. Please retry uploading in a moment.",
                    code="DATABASE_BUSY",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            raise
        except Exception:
            logger.exception("Direct storage upload failed")
            raise

        return api_response(
            data=MediaFileSerializer(media_file, context={'request': request}).data,
            message="Media uploaded successfully and registered in storage engine.",
            status_code=status.HTTP_201_CREATED
        )

#--------------------------------------------------------------
# Confirm Upload View
#--------------------------------------------------------------

class ConfirmUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, upload_id):
        acad_uuid = safe_get_user_academy_id(request.user)
        try:
            session = UploadSession.objects.get(id=upload_id, academy_uuid=acad_uuid)
        except UploadSession.DoesNotExist:
            raise CubixSkillAPIException("Upload session not found.", code="NOT_FOUND", status_code=404)

        media_file = StorageService.confirm_upload(session)
        return api_response(
            data=MediaFileSerializer(media_file).data,
            message="Upload confirmed and media registered."
        )

from rest_framework.parsers import JSONParser

#--------------------------------------------------------------
# MediaFile ViewSet
#--------------------------------------------------------------

class MediaFileViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = MediaFileSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_parsers(self):
        action = getattr(self, 'action', None)
        if action in ['create', 'update', 'partial_update']:
            return [MultiPartParser(), FormParser()]
        return [JSONParser(), MultiPartParser(), FormParser()]

    def get_queryset(self):
        acad_uuid = safe_get_user_academy_id(self.request.user)
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

    @action(detail=True, methods=['post'], url_path='convert-hls')
    def convert_hls(self, request, pk=None):
        media_file = self.get_object()
        if media_file.media_type != 'VIDEO':
            raise CubixSkillAPIException("Only video media files can be converted to HLS.", code="NOT_A_VIDEO", status_code=status.HTTP_400_BAD_REQUEST)

        from storage.models import ProcessingMode, ProcessingStatus
        media_file.processing_mode = ProcessingMode.HLS
        media_file.processing_status = ProcessingStatus.QUEUED
        media_file.processing_progress = 5
        media_file.processing_error = ''
        media_file.save(update_fields=['processing_mode', 'processing_status', 'processing_progress', 'processing_error'])

        from storage.tasks import process_video_transcoding_task
        media_id = str(media_file.id)
        transaction.on_commit(lambda: process_video_transcoding_task.delay(media_id))

        return api_response(
            data=MediaFileSerializer(media_file, context={'request': request}).data,
            message="On-demand HLS conversion queued successfully."
        )

    def destroy(self, request, *args, **kwargs):
        media_file = self.get_object()
        force = request.query_params.get('force', 'false').lower() in ('true', '1')
        hard_delete = request.query_params.get('hard', 'false').lower() in ('true', '1')

        from storage.selectors import MediaUsageSelector
        usage_data = MediaUsageSelector.get_usage(media_file)
        usage_count = usage_data.get('usage_count', 0)

        if usage_count > 0 and not force:
            refs = usage_data.get('references', [])
            ref_locations = ", ".join([f"{r.get('context') or r.get('type')}" for r in refs[:3]])
            raise CubixSkillAPIException(
                f"Cannot delete asset '{media_file.display_name or media_file.original_filename}'. It is currently in use in {usage_count} location(s) ({ref_locations}). Please unlink or replace this file before deleting.",
                code="MEDIA_IN_USE",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        StorageService.delete_media_file(media_file, hard_delete=hard_delete)
        return api_response(message="Media file safely deleted from storage and database.")

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        file_ids = request.data.get('file_ids', [])
        if not isinstance(file_ids, list) or not file_ids:
            raise CubixSkillAPIException("Please provide a valid list of 'file_ids' to delete.", code="INVALID_PAYLOAD", status_code=status.HTTP_400_BAD_REQUEST)

        user_academy_id = safe_get_user_academy_id(request.user)
        is_super = getattr(request.user, 'role_code', '') in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']

        qs = MediaFile.objects.filter(id__in=file_ids).exclude(status=MediaStatus.DELETED)
        if not is_super and user_academy_id:
            qs = qs.filter(academy_uuid=user_academy_id)

        found_files = {str(f.id): f for f in qs}

        deleted_ids = []
        blocked_items = []
        failed_count = 0

        from storage.selectors import MediaUsageSelector

        import time
        from django.db import OperationalError

        for fid in file_ids:
            fid_str = str(fid)
            if fid_str not in found_files:
                failed_count += 1
                continue

            media_file = found_files[fid_str]
            usage_data = MediaUsageSelector.get_usage(media_file)
            if usage_data.get('is_used', False):
                refs = usage_data.get('references', [])
                ref_str = ", ".join([f"{r.get('context') or r.get('type')}" for r in refs[:3]])
                blocked_items.append({
                    "id": fid_str,
                    "filename": media_file.display_name or media_file.original_filename,
                    "reason": f"In use in {len(refs)} location(s) ({ref_str})",
                    "references": refs
                })
            else:
                success = False
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        StorageService.delete_media_file(media_file, hard_delete=False)
                        deleted_ids.append(fid_str)
                        success = True
                        break
                    except OperationalError as op_err:
                        if 'locked' in str(op_err).lower() and attempt < max_retries - 1:
                            logger.warning(f"SQLite database locked deleting file {fid_str}, retrying (attempt {attempt + 1}/{max_retries})...")
                            time.sleep(0.1 * (2 ** attempt))
                            continue
                        logger.exception(f"Bulk delete OperationalError for file {fid_str}: {op_err}")
                        break
                    except Exception as err:
                        logger.exception(f"Bulk delete error for file {fid_str}: {err}")
                        break

                if not success:
                    failed_count += 1

        return api_response(
            data={
                "deleted_ids": deleted_ids,
                "deleted_count": len(deleted_ids),
                "blocked_items": blocked_items,
                "blocked_count": len(blocked_items),
                "failed_count": failed_count,
                "total_requested": len(file_ids)
            },
            message=f"Bulk delete finished. Successfully deleted {len(deleted_ids)} asset(s), {len(blocked_items)} blocked due to active usage."
        )

#--------------------------------------------------------------
# Storage Usage & History View
#--------------------------------------------------------------

class StorageUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        acad_uuid = safe_get_user_academy_id(request.user)
        if not acad_uuid and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.selectors import StorageSummarySelector
        from storage.utils import format_bytes

        summary = StorageSummarySelector.get_summary(acad_uuid)
        summary['used_display'] = format_bytes(summary['used_bytes'])

        return api_response(data=summary)


class StorageCurrentPeriodView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        acad_uuid = safe_get_user_academy_id(request.user)
        if not acad_uuid and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.metering import StorageBillingService, StorageMeteringService
        from storage.utils import format_bytes

        account = StorageMeteringService.get_or_create_account(acad_uuid)
        current_record = StorageBillingService.close_billing_period(acad_uuid)

        from decimal import Decimal
        bytes_in_gb = Decimal(1073741824)
        gb_hours = (Decimal(str(current_record.total_byte_seconds)) / (bytes_in_gb * Decimal(3600))).quantize(Decimal('0.0001'))
        gb_days = (Decimal(str(current_record.total_byte_seconds)) / (bytes_in_gb * Decimal(86400))).quantize(Decimal('0.0001'))

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
        acad_uuid = safe_get_user_academy_id(request.user)
        if not acad_uuid and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.metering import StorageBillingService

        # Ensure today's rollup is built
        StorageBillingService.build_daily_rollup(acad_uuid)

        rollups = StorageUsageRollup.objects.filter(academy_uuid=acad_uuid, interval_type='DAILY').order_by('-period_start')[:30]
        return api_response(data=StorageUsageRollupSerializer(rollups, many=True).data)


class StorageMonthlyBillingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.models import StorageUsageCharge
        from storage.serializers import StorageUsageChargeSerializer

        charges = StorageUsageCharge.objects.filter(academy=academy).order_by('-billing_ended_at')
        return api_response(data=StorageUsageChargeSerializer(charges, many=True).data)


#--------------------------------------------------------------
# Storage Billing System Production Dashboard Views
#--------------------------------------------------------------

class StorageSummaryDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from decimal import Decimal

        from django.utils import timezone
        from storage.models import (
            AcademyStorageUsage,
            StorageBillingCycle,
            StorageBillingCycleStatus,
            StorageBillingSettings,
        )
        from storage.utils import (
            get_interval_label,
            get_next_credit_debit_datetime,
            storage_interval_delta,
        )

        settings_obj = StorageBillingSettings.get_settings()

        # Reconcile AcademyStorageUsage from authoritative active MediaFiles
        from storage.models import MediaFile, MediaStatus
        from django.db.models import Sum
        active_qs = MediaFile.objects.filter(academy_uuid=academy.id).exclude(status=MediaStatus.DELETED)
        actual_used_bytes = active_qs.aggregate(total=Sum('size_bytes'))['total'] or 0
        actual_file_count = active_qs.count()

        usage, _ = AcademyStorageUsage.objects.get_or_create(
            academy=academy,
            defaults={'academy_uuid': academy.id, 'used_bytes': actual_used_bytes, 'file_count': actual_file_count}
        )
        if usage.used_bytes != actual_used_bytes or usage.file_count != actual_file_count:
            usage.used_bytes = actual_used_bytes
            usage.file_count = actual_file_count
            usage.save(update_fields=['used_bytes', 'file_count'])

        now = timezone.now()
        BYTES_PER_GB = Decimal(1024 ** 3)
        current_gb = Decimal(usage.used_bytes) / BYTES_PER_GB
        rate_per_gb = settings_obj.storage_credit_rate_per_gb

        interval_str = settings_obj.storage_billing_interval
        delta = storage_interval_delta(interval_str)
        interval_label = get_interval_label(interval_str)

        last_metered_at = usage.last_billed_at
        next_meter_at = (last_metered_at + delta) if last_metered_at else (now + delta)
        next_credit_debit_at = get_next_credit_debit_datetime(settings_obj, now=timezone.localtime())

        open_cycle = StorageBillingCycle.objects.filter(
            academy=academy,
            status=StorageBillingCycleStatus.OPEN
        ).order_by('-cycle_start_at').first()

        current_accumulated = open_cycle.accumulated_credits if open_cycle else Decimal("0.0000")
        current_meter_count = open_cycle.meter_records.count() if open_cycle else 0

        last_debited_cycle = StorageBillingCycle.objects.filter(
            academy=academy,
            status__in=[StorageBillingCycleStatus.SETTLED, StorageBillingCycleStatus.DEBITED]
        ).order_by('-settled_at', '-debited_at', '-created_at').first()

        from storage.services import StorageOutstandingService
        outstanding_credits = StorageOutstandingService.get_total_outstanding_credits(academy)
        has_outstanding = (outstanding_credits > Decimal("0.0000"))

        last_successful_debit_at = (last_debited_cycle.settled_at or last_debited_cycle.debited_at) if last_debited_cycle else None
        last_settlement_status = last_debited_cycle.settlement_status if (last_debited_cycle and last_debited_cycle.settlement_status) else ("PAID" if last_debited_cycle else None)

        return api_response(data={
            "billing_enabled": settings_obj.storage_billing_enabled,
            "metering_interval": interval_str,
            "billing_interval": interval_str,
            "billing_interval_label": interval_label,
            "credit_rate_per_gb": f"{rate_per_gb:.4f}",
            "debit_day": settings_obj.storage_credit_debit_day,
            "debit_time": settings_obj.storage_credit_debit_time.strftime("%H:%M:%S") if settings_obj.storage_credit_debit_time else "00:00:00",
            "current_storage_bytes": usage.used_bytes,
            "current_storage_gb": f"{current_gb:.2f}",
            "file_count": usage.file_count,
            "current_cycle_accumulated_credits": f"{current_accumulated:.4f}",
            "current_cycle_meter_count": current_meter_count,
            "outstanding_storage_credits": f"{outstanding_credits:.4f}",
            "has_outstanding_storage_balance": has_outstanding,
            "last_settlement_status": last_settlement_status,
            "previous_settlement_at": last_successful_debit_at.isoformat() if last_successful_debit_at else None,
            "next_settlement_at": next_credit_debit_at.isoformat() if next_credit_debit_at else None,
            "last_metered_at": last_metered_at.isoformat() if last_metered_at else None,
            "next_meter_at": next_meter_at.isoformat() if next_meter_at else None,
            "next_credit_debit_at": next_credit_debit_at.isoformat() if next_credit_debit_at else None,
            "last_successful_debit_at": last_successful_debit_at.isoformat() if last_successful_debit_at else None,
            "last_billed_at": last_metered_at.isoformat() if last_metered_at else None,
            "last_debited_at": last_successful_debit_at.isoformat() if last_successful_debit_at else None,
            "next_billing_at": next_meter_at.isoformat() if next_meter_at else None,
        })


class StorageSnapshotsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.models import AcademyStorageSnapshot
        from storage.serializers import AcademyStorageSnapshotSerializer

        snapshots = AcademyStorageSnapshot.objects.filter(academy=academy).order_by('-captured_at')[:100]
        return api_response(data=AcademyStorageSnapshotSerializer(snapshots, many=True).data)


class StorageBillingPeriodsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from storage.models import StorageUsageCharge
        from storage.serializers import StorageUsageChargeSerializer

        charges = StorageUsageCharge.objects.filter(academy=academy).order_by('-billing_ended_at')
        return api_response(data=StorageUsageChargeSerializer(charges, many=True).data)


class ControlPanelStorageSettingsView(APIView):
    """Read and change platform storage pricing (not academy-specific settings)."""
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def _require_admin(request):
        if request.user.role_code not in ("SUPER_ADMIN", "SUPER_ADMIN_STAFF") and not request.user.is_superuser:
            raise CubixSkillAPIException(
                "Only Super Admins can manage platform storage settings.",
                code="PERMISSION_DENIED", status_code=status.HTTP_403_FORBIDDEN,
            )

    def get(self, request):
        self._require_admin(request)
        from storage.models import StorageBillingSettings
        from storage.serializers import StorageBillingSettingsSerializer

        settings_obj = StorageBillingSettings.get_settings()
        return api_response(data=StorageBillingSettingsSerializer(settings_obj).data)

    def post(self, request):
        self._require_admin(request)
        from django.conf import settings as django_settings
        from django.db import transaction
        from rest_framework.exceptions import ValidationError
        from storage.models import StorageBillingSettings
        from storage.serializers import StorageBillingSettingsSerializer, StorageBillingSettingsUpdateSerializer

        data = request.data.copy()
        aliases = {
            "billing_enabled": "storage_billing_enabled",
            "billing_interval": "storage_billing_interval",
            "credit_rate_per_gb": "storage_credit_rate_per_gb",
            "credits_per_gb_month": "storage_credit_rate_per_gb",
        }
        for previous, current in aliases.items():
            if previous in data:
                if current in data and str(data[previous]) != str(data[current]):
                    raise ValidationError({current: "Conflicting storage setting values."})
                if current not in data:
                    data[current] = data[previous]

        serializer = StorageBillingSettingsUpdateSerializer(data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data
        if not changes:
            raise ValidationError({"message": "No storage setting values provided."})

        with transaction.atomic():
            settings_obj = StorageBillingSettings.get_settings()
            old_data = StorageBillingSettingsSerializer(settings_obj).data
            for key, value in changes.items():
                setattr(settings_obj, key, value)
            if (settings_obj.storage_billing_enabled
                    and settings_obj.storage_billing_interval == "10_SECONDS"
                    and not django_settings.STORAGE_ALLOW_10_SECOND_METERING):
                raise ValidationError({
                    "storage_billing_interval": "10-second metering is prohibited in production.",
                })
            settings_obj.full_clean()
            settings_obj.save(update_fields=list(changes.keys()) + ["updated_at"])
            new_data = StorageBillingSettingsSerializer(settings_obj).data

        try:
            from audit_logs.models import AuditLog, AuditAction, AuditCategory
            AuditLog.objects.create(
                actor=request.user,
                actor_display=request.user.email,
                actor_role=str(getattr(request.user, "role_code", "") or ""),
                action=AuditAction.STORAGE_CORRECTED,
                category=AuditCategory.STORAGE,
                target_type="StorageBillingSettings",
                target_id=str(settings_obj.id),
                description="Platform storage credit billing policy updated.",
                changes={"old": old_data, "new": new_data},
            )
        except Exception:
            logger.warning("Storage settings saved, but audit logging failed.", exc_info=True)

        return api_response(
            data=new_data,
            message="Storage billing settings updated successfully.",
        )


class StorageMeterLogsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        from django.core.paginator import Paginator
        from storage.models import StorageMeterRecord
        from storage.serializers import StorageMeterRecordSerializer

        qs = StorageMeterRecord.objects.filter(academy=academy).order_by('-metered_at')

        raw_month = request.GET.get('month')
        raw_year = request.GET.get('year')
        if raw_month and str(raw_month).isdigit():
            qs = qs.filter(metered_at__month=int(raw_month))
        if raw_year and str(raw_year).isdigit():
            qs = qs.filter(metered_at__year=int(raw_year))

        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 25))

        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)

        serialized = StorageMeterRecordSerializer(page_obj.object_list, many=True).data

        return api_response(data={
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "page": page_obj.number,
            "page_size": page_size,
            "results": serialized
        })


class StorageSettlementHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")
        import calendar
        from decimal import Decimal

        from django.core.paginator import Paginator
        from django.db.models import Q
        from django.utils import timezone
        from storage.models import StorageBillingCycle, StorageBillingCycleStatus
        from storage.serializers import StorageBillingCycleSerializer

        qs = StorageBillingCycle.objects.filter(
            academy=academy,
            status__in=[StorageBillingCycleStatus.SETTLED, StorageBillingCycleStatus.DEBITED]
        ).order_by('-settled_at', '-debited_at', '-created_at')

        now = timezone.localtime()
        raw_month = request.GET.get('month')
        raw_year = request.GET.get('year')

        selected_month = int(raw_month) if (raw_month and str(raw_month).isdigit()) else now.month
        selected_year = int(raw_year) if (raw_year and str(raw_year).isdigit()) else now.year

        filtered_qs = qs.filter(
            Q(settled_at__year=selected_year, settled_at__month=selected_month) |
            Q(debited_at__year=selected_year, debited_at__month=selected_month) |
            Q(created_at__year=selected_year, created_at__month=selected_month)
        ).distinct()

        month_name = calendar.month_name[selected_month] if 1 <= selected_month <= 12 else ''
        period_label = f"{month_name} {selected_year}".strip()

        total_settlements = filtered_qs.count()
        sum_billed = sum((c.original_amount if c.original_amount > 0 else c.accumulated_credits for c in filtered_qs), Decimal("0.0000")) if total_settlements > 0 else Decimal("0.0000")
        sum_paid = sum((c.paid_amount for c in filtered_qs), Decimal("0.0000")) if total_settlements > 0 else Decimal("0.0000")
        sum_outstanding = sum((c.outstanding_amount for c in filtered_qs), Decimal("0.0000")) if total_settlements > 0 else Decimal("0.0000")

        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 25))

        paginator = Paginator(filtered_qs, page_size)
        page_obj = paginator.get_page(page)

        serialized = StorageBillingCycleSerializer(page_obj.object_list, many=True).data

        return api_response(data={
            "period_label": period_label,
            "total_settlements": total_settlements,
            "storage_billed": f"{sum_billed:.4f}",
            "credits_paid": f"{sum_paid:.4f}",
            "outstanding": f"{sum_outstanding:.4f}",
            "credits_debited": f"{sum_paid:.4f}",
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "page": page_obj.number,
            "page_size": page_size,
            "results": serialized
        })


class StorageMeterFileInventoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, meter_id):
        academy = safe_get_user_academy(request.user)
        if not academy and getattr(request.user, 'role_code', '') not in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            raise CubixSkillAPIException("No academy linked to authenticated user.", code="NO_ACADEMY")

        from django.db import models
        from storage.models import MediaFile, MediaStatus, StorageMeterFileSnapshot, StorageMeterRecord
        from storage.utils import format_bytes

        try:
            meter_record = StorageMeterRecord.objects.get(id=meter_id, academy=academy)
        except (StorageMeterRecord.DoesNotExist, ValueError):
            raise CubixSkillAPIException("Storage meter record not found.", code="NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)

        snapshots = list(StorageMeterFileSnapshot.objects.filter(meter_record=meter_record))

        if snapshots:
            files = [
                {
                    "id": str(s.media_file_uuid),
                    "original_filename": s.filename_snapshot,
                    "display_name": s.filename_snapshot,
                    "file_type": s.media_type_snapshot,
                    "media_type": s.media_type_snapshot,
                    "size_bytes": s.size_bytes_snapshot,
                    "formatted_size": format_bytes(s.size_bytes_snapshot),
                    "created_at": s.uploaded_at_snapshot.isoformat() if s.uploaded_at_snapshot else None,
                    "uploaded_at": s.uploaded_at_snapshot.isoformat() if s.uploaded_at_snapshot else None,
                }
                for s in snapshots
            ]
            has_history = True
            msg = "File inventory retrieved from snapshot."
        else:
            metered_at = meter_record.metered_at
            active_files_qs = MediaFile.objects.filter(
                academy_uuid=academy.id,
                created_at__lte=metered_at
            ).filter(
                models.Q(deleted_at__isnull=True) | models.Q(deleted_at__gt=metered_at)
            ).exclude(status=MediaStatus.PENDING)

            if active_files_qs.exists() or meter_record.used_bytes == 0:
                files = [
                    {
                        "id": str(f.id),
                        "original_filename": f.original_filename,
                        "display_name": f.display_name or f.original_filename,
                        "file_type": f.file_type or f.file_extension or f.media_type,
                        "media_type": f.media_type,
                        "size_bytes": f.total_storage_bytes or f.size_bytes,
                        "formatted_size": format_bytes(f.total_storage_bytes or f.size_bytes),
                        "created_at": (f.uploaded_at or f.created_at).isoformat() if (f.uploaded_at or f.created_at) else None,
                        "uploaded_at": (f.uploaded_at or f.created_at).isoformat() if (f.uploaded_at or f.created_at) else None,
                    }
                    for f in active_files_qs
                ]
                has_history = True
                msg = "File inventory reconstructed from historical records."
            else:
                return api_response(data={
                    "has_file_history": False,
                    "message": "File-level history is unavailable for this metered record.",
                    "meter_record": {
                        "id": str(meter_record.id),
                        "metered_at": meter_record.metered_at.isoformat(),
                        "used_bytes": meter_record.used_bytes,
                        "used_gb": str(meter_record.used_gb),
                        "calculated_credits": str(meter_record.calculated_credits),
                    },
                    "total_files": 0,
                    "total_storage_bytes": 0,
                    "formatted_total_storage": "0 B",
                    "accounting_difference_bytes": 0,
                    "files": []
                })

        total_storage_size = sum(f["size_bytes"] for f in files)
        diff_bytes = total_storage_size - meter_record.used_bytes

        return api_response(data={
            "has_file_history": has_history,
            "message": msg,
            "meter_record": {
                "id": str(meter_record.id),
                "metered_at": meter_record.metered_at.isoformat(),
                "used_bytes": meter_record.used_bytes,
                "used_gb": str(meter_record.used_gb),
                "calculated_credits": str(meter_record.calculated_credits),
            },
            "total_files": len(files),
            "total_storage_bytes": total_storage_size,
            "formatted_total_storage": format_bytes(total_storage_size),
            "accounting_difference_bytes": diff_bytes,
            "files": files
        })



