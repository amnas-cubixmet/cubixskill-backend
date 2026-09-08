import logging
from decimal import Decimal

from credits.services import CreditPricingService
from storage.metering import StorageMeteringService
from storage.models import StorageStreamingProfile
from storage.utils import format_bytes

logger = logging.getLogger(__name__)

class StorageEstimateService:
    @classmethod
    def calculate_pre_upload_estimate(
        cls,
        filename: str,
        file_size_bytes: int,
        mime_type: str,
        academy_uuid,
        duration_seconds: float = None,
        width: int = None,
        height: int = None,
        adaptive_streaming_enabled: bool = True
    ) -> dict:
        """
        Calculates pre-upload persistent storage and Credit cost estimate for any file upload.
        Reads backend active storage rates and HLS profiles without relying on hardcoded client logic.
        """
        mime = (mime_type or '').lower()
        is_video = ('video' in mime) or filename.lower().endswith(('.mp4', '.mov', '.webm', '.mkv', '.avi'))

        # Fetch active storage Credit rate (STORAGE_MONTHLY)
        rate = CreditPricingService.get_rate('STORAGE_MONTHLY')
        rate_cost = rate.credit_cost if rate else Decimal('10.0000')

        # Get current stored bytes for the Academy
        account = StorageMeteringService.get_or_create_account(academy_uuid)
        current_storage_bytes = account.current_usage_bytes

        if not is_video or not adaptive_streaming_enabled:
            estimated_source_bytes = file_size_bytes
            estimated_streaming_bytes = 0
            estimated_total_bytes = file_size_bytes

            bytes_in_gb = Decimal(1073741824)
            gb_count = Decimal(str(estimated_total_bytes)) / bytes_in_gb
            estimated_monthly_credits = (gb_count * rate_cost).quantize(Decimal('0.0001'))
            estimated_daily_credits = (estimated_monthly_credits / Decimal(30)).quantize(Decimal('0.0001'))

            return {
                "filename": filename,
                "file_size_bytes": file_size_bytes,
                "file_size_display": format_bytes(file_size_bytes),
                "is_video": is_video,
                "duration_seconds": round(duration_seconds, 2) if (duration_seconds and duration_seconds > 0) else 0,
                "width": width or 0,
                "height": height or 0,
                "resolution_display": f"{height}p" if (height and height > 0) else "Original",
                "estimated_source_bytes": estimated_source_bytes,
                "estimated_source_display": format_bytes(estimated_source_bytes),
                "estimated_streaming_bytes": 0,
                "estimated_streaming_display": "0 B",
                "estimated_total_bytes": estimated_total_bytes,
                "estimated_total_display": format_bytes(estimated_total_bytes),
                "current_storage_bytes": current_storage_bytes,
                "current_storage_display": format_bytes(current_storage_bytes),
                "projected_storage_bytes": current_storage_bytes + estimated_total_bytes,
                "projected_storage_display": format_bytes(current_storage_bytes + estimated_total_bytes),
                "rate_cost": str(rate_cost),
                "rate_display": f"{rate_cost} Credits / GB",
                "estimated_monthly_credits": str(estimated_monthly_credits),
                "estimated_daily_credits": str(estimated_daily_credits),
                "daily_cost_display": f"{estimated_daily_credits} Credits / day",
                "adaptive_streaming_enabled": adaptive_streaming_enabled if is_video else False,
                "planned_qualities": [],
                "renditions": []
            }

        # Video Estimation Logic
        duration = duration_seconds if (duration_seconds and duration_seconds > 0) else 60.0
        src_width = width if (width and width > 0) else 1280
        src_height = height if (height and height > 0) else 720

        resolution_label = f"{src_height}p"

        # Profiles capped by source height (no upscaling)
        if not StorageStreamingProfile.objects.exists():
            from django.core.management import call_command
            call_command('init_streaming_profiles')

        profiles = StorageStreamingProfile.objects.filter(
            is_enabled=True,
            height__lte=src_height
        ).order_by('-height')

        if not profiles.exists():
            profiles = StorageStreamingProfile.objects.filter(is_enabled=True).order_by('height')[:1]

        planned_qualities = []
        renditions_list = []
        estimated_streaming_bytes = 0

        for prof in profiles:
            planned_qualities.append(prof.quality_label)
            # Rendition size = (video_bitrate + audio_bitrate) * 1000 * duration / 8
            total_bitrate_bps = (prof.video_bitrate_kbps + prof.audio_bitrate_kbps) * 1000
            rend_bytes = int((total_bitrate_bps * duration) / 8)
            estimated_streaming_bytes += rend_bytes

            renditions_list.append({
                "quality_label": prof.quality_label,
                "width": prof.width,
                "height": prof.height,
                "video_bitrate_kbps": prof.video_bitrate_kbps,
                "audio_bitrate_kbps": prof.audio_bitrate_kbps,
                "estimated_bytes": rend_bytes,
                "estimated_display": format_bytes(rend_bytes)
            })

        estimated_source_bytes = file_size_bytes
        estimated_total_bytes = estimated_source_bytes + estimated_streaming_bytes

        bytes_in_gb = Decimal(1073741824)
        gb_count = Decimal(str(estimated_total_bytes)) / bytes_in_gb
        estimated_monthly_credits = (gb_count * rate_cost).quantize(Decimal('0.0001'))
        estimated_daily_credits = (estimated_monthly_credits / Decimal(30)).quantize(Decimal('0.0001'))

        return {
            "filename": filename,
            "file_size_bytes": file_size_bytes,
            "file_size_display": format_bytes(file_size_bytes),
            "is_video": True,
            "duration_seconds": round(duration, 2),
            "width": src_width,
            "height": src_height,
            "resolution_display": resolution_label,
            "estimated_source_bytes": estimated_source_bytes,
            "estimated_source_display": format_bytes(estimated_source_bytes),
            "estimated_streaming_bytes": estimated_streaming_bytes,
            "estimated_streaming_display": format_bytes(estimated_streaming_bytes),
            "estimated_total_bytes": estimated_total_bytes,
            "estimated_total_display": format_bytes(estimated_total_bytes),
            "current_storage_bytes": current_storage_bytes,
            "current_storage_display": format_bytes(current_storage_bytes),
            "projected_storage_bytes": current_storage_bytes + estimated_total_bytes,
            "projected_storage_display": format_bytes(current_storage_bytes + estimated_total_bytes),
            "rate_cost": str(rate_cost),
            "rate_display": f"{rate_cost} Credits / GB",
            "estimated_monthly_credits": str(estimated_monthly_credits),
            "estimated_daily_credits": str(estimated_daily_credits),
            "daily_cost_display": f"{estimated_daily_credits} Credits / day",
            "adaptive_streaming_enabled": True,
            "planned_qualities": planned_qualities,
            "renditions": renditions_list
        }
