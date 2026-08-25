from django.core.management.base import BaseCommand
from storage.models import StorageStreamingProfile

DEFAULT_PROFILES = [
    {"quality_label": "1080p", "width": 1920, "height": 1080, "video_bitrate_kbps": 5000, "audio_bitrate_kbps": 128, "order_index": 1},
    {"quality_label": "720p",  "width": 1280, "height": 720,  "video_bitrate_kbps": 2500, "audio_bitrate_kbps": 128, "order_index": 2},
    {"quality_label": "480p",  "width": 854,  "height": 480,  "video_bitrate_kbps": 1200, "audio_bitrate_kbps": 128, "order_index": 3},
    {"quality_label": "360p",  "width": 640,  "height": 360,  "video_bitrate_kbps": 700,  "audio_bitrate_kbps": 96,  "order_index": 4},
    {"quality_label": "240p",  "width": 426,  "height": 240,  "video_bitrate_kbps": 300,  "audio_bitrate_kbps": 64,  "order_index": 5},
    {"quality_label": "144p",  "width": 256,  "height": 144,  "video_bitrate_kbps": 150,  "audio_bitrate_kbps": 64,  "order_index": 6},
]

class Command(BaseCommand):
    help = "Seed standard HLS adaptive streaming profiles for CubixSkill"

    def handle(self, *args, **options):
        created_count = 0
        for p in DEFAULT_PROFILES:
            profile, created = StorageStreamingProfile.objects.get_or_create(
                quality_label=p["quality_label"],
                defaults={
                    "width": p["width"],
                    "height": p["height"],
                    "video_bitrate_kbps": p["video_bitrate_kbps"],
                    "audio_bitrate_kbps": p["audio_bitrate_kbps"],
                    "is_enabled": True,
                    "order_index": p["order_index"],
                }
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully initialized HLS streaming profiles ({created_count} new created, {len(DEFAULT_PROFILES)} total)."))
