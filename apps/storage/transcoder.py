import glob
import json
import logging
import os
import shutil
import subprocess
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from storage.metering import StorageMeteringService
from storage.models import (
    MediaFile,
    ProcessingStatus,
    StorageStreamingProfile,
    UsageEventType,
    VideoRendition,
)

logger = logging.getLogger(__name__)


def executable_exists(value: str | None) -> bool:
    if not value:
        return False
    return bool(os.path.isfile(value) or shutil.which(value))


def get_ffmpeg_binary() -> str | None:
    custom = getattr(settings, 'FFMPEG_BINARY', None) or os.getenv('FFMPEG_BINARY')
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if found:
        return found
    # WinGet auto-discovery
    winget_pattern = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "WinGet", "Packages", "*", "*", "bin", "ffmpeg.exe")
    winget_matches = glob.glob(winget_pattern)
    if winget_matches and os.path.isfile(winget_matches[0]):
        return winget_matches[0]
    try:
        import importlib.util
        if importlib.util.find_spec('imageio_ffmpeg') is not None:
            mod = importlib.import_module('imageio_ffmpeg')
            exe = getattr(mod, 'get_ffmpeg_exe', lambda: None)()
            if exe and os.path.isfile(exe):
                return exe
    except Exception:
        pass
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    return None


def get_ffprobe_binary() -> str | None:
    custom = getattr(settings, 'FFPROBE_BINARY', None) or os.getenv('FFPROBE_BINARY')
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which('ffprobe') or shutil.which('ffprobe.exe')
    if found:
        return found
    # WinGet auto-discovery
    winget_pattern = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "WinGet", "Packages", "*", "*", "bin", "ffprobe.exe")
    winget_matches = glob.glob(winget_pattern)
    if winget_matches and os.path.isfile(winget_matches[0]):
        return winget_matches[0]
    ffmpeg_exe = get_ffmpeg_binary()
    if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
        dir_name = os.path.dirname(ffmpeg_exe)
        possible_ffprobe = os.path.join(dir_name, "ffprobe.exe")
        if os.path.isfile(possible_ffprobe):
            return possible_ffprobe
        possible_ffprobe_linux = os.path.join(dir_name, "ffprobe")
        if os.path.isfile(possible_ffprobe_linux):
            return possible_ffprobe_linux
    common_paths = [
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\tools\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffprobe.exe"),
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    return None


def check_video_processor_available() -> tuple[bool, bool]:
    ffmpeg_bin = get_ffmpeg_binary()
    ffprobe_bin = get_ffprobe_binary()
    ffmpeg_ok = executable_exists(ffmpeg_bin)
    ffprobe_ok = executable_exists(ffprobe_bin)
    return ffmpeg_ok, ffprobe_ok


class VideoTranscoder:
    @classmethod
    def validate_hls_segment(cls, segment_path: str) -> None:
        """
        Uses ffprobe to verify that segment_path is a valid MPEG-TS segment containing an H.264 video stream.
        """
        ffprobe_bin = get_ffprobe_binary()
        if not executable_exists(ffprobe_bin):
            raise RuntimeError(f"FFprobe executable not found for segment validation: {ffprobe_bin}")

        if not os.path.isfile(segment_path) or os.path.getsize(segment_path) < 50:
            raise RuntimeError(f"Generated HLS segment file is missing or empty: {os.path.basename(segment_path)}")

        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-print_format', 'json',
            '-show_streams',
            '-show_format',
            segment_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            err = result.stderr.strip()[-300:] if result.stderr else "ffprobe failed on segment"
            raise RuntimeError(f"Generated HLS segment is invalid ({os.path.basename(segment_path)}): {err}")

        data = json.loads(result.stdout or '{}')
        streams = data.get('streams', [])
        video_streams = [s for s in streams if s.get('codec_type') == 'video']
        if not video_streams:
            raise RuntimeError(f"Generated HLS segment contains no video stream: {os.path.basename(segment_path)}")

        codec = video_streams[0].get('codec_name')
        if codec != 'h264':
            raise RuntimeError(f"Unexpected HLS video codec '{codec}' in segment (expected h264).")

    @classmethod
    def probe_video_metadata(cls, file_path: str) -> dict:
        """
        Uses ffprobe to extract width, height, duration_seconds, video/audio codecs.
        """
        ffprobe_bin = get_ffprobe_binary()
        if not executable_exists(ffprobe_bin):
            raise RuntimeError(f"FFprobe executable not found or not in PATH: {ffprobe_bin}")

        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            err_msg = result.stderr.strip()[-1000:] if result.stderr else "ffprobe failed with exit code 1"
            raise RuntimeError(f"ffprobe metadata extraction failed for '{file_path}': {err_msg}")

        data = json.loads(result.stdout or '{}')
        streams = data.get('streams', [])
        format_info = data.get('format', {})

        video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
        if not video_stream:
            raise RuntimeError(f"No video stream found in file '{file_path}'.")

        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Invalid video dimensions ({width}x{height}) in '{file_path}'.")

        duration_val = format_info.get('duration') or video_stream.get('duration') or 10.0
        duration_seconds = Decimal(str(round(float(duration_val), 2)))

        audio_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)

        return {
            'width': width,
            'height': height,
            'duration_seconds': duration_seconds,
            'video_codec': video_stream.get('codec_name', 'h264'),
            'audio_codec': audio_stream.get('codec_name', 'aac') if audio_stream else None,
            'bitrate': int(format_info.get('bit_rate', 2500000))
        }

    @classmethod
    def get_supported_profiles(cls, source_width: int, source_height: int):
        """
        Returns active StorageStreamingProfile items where target height <= min(source_width, source_height).
        Prevents upscaling above source resolution.
        """
        if not StorageStreamingProfile.objects.filter(is_enabled=True).exists():
            StorageStreamingProfile.ensure_default_profiles()

        effective_source = min(source_width, source_height)
        profiles = StorageStreamingProfile.objects.filter(
            is_enabled=True,
            height__lte=effective_source
        ).order_by('-height')

        if not profiles.exists():
            profiles = StorageStreamingProfile.objects.filter(is_enabled=True).order_by('height')[:1]
        return profiles

    @classmethod
    def process_media_video(cls, media_file_id) -> MediaFile:
        """
        Executes real FFmpeg HLS video transcoding for media_file_id via Celery with strict ffprobe validation.
        """
        from django.db import connection
        qs = MediaFile.objects
        if connection.vendor != 'sqlite':
            qs = qs.select_for_update()
        media_file = qs.get(id=media_file_id)

        ffmpeg_bin = get_ffmpeg_binary()
        ffprobe_bin = get_ffprobe_binary()

        logger.info(
            "Starting HLS processing media=%s ffmpeg=%s ffprobe=%s",
            media_file_id, ffmpeg_bin, ffprobe_bin
        )

        if media_file.processing_status == ProcessingStatus.READY and media_file.stream_manifest_key:
            master_abs = os.path.join(settings.MEDIA_ROOT, media_file.stream_manifest_key)
            if os.path.exists(master_abs) and os.path.getsize(master_abs) > 50:
                hls_dir = os.path.dirname(master_abs)
                segments = glob.glob(os.path.join(hls_dir, "*", "*.ts"))
                if len(segments) >= 1:
                    try:
                        cls.validate_hls_segment(segments[0])
                        return media_file
                    except Exception:
                        logger.warning(f"Existing READY HLS for media {media_file.id} is invalid. Re-transcoding.")

        media_file.processing_status = ProcessingStatus.PROCESSING
        media_file.processing_progress = 10
        media_file.save(update_fields=['processing_status', 'processing_progress'])

        source_path = media_file.storage_path
        if not os.path.exists(source_path):
            media_file.processing_status = ProcessingStatus.FAILED
            media_file.processing_error = f"Source file does not exist on disk: {source_path}"
            media_file.save(update_fields=['processing_status', 'processing_error'])
            return media_file

        if not executable_exists(ffmpeg_bin):
            err_msg = f"FFmpeg executable not found or invalid: {ffmpeg_bin}"
            logger.error(f"Transcoding failed for media {media_file_id}: {err_msg}")
            media_file.processing_status = ProcessingStatus.FAILED
            media_file.processing_error = err_msg
            media_file.save(update_fields=['processing_status', 'processing_error'])
            return media_file

        if not executable_exists(ffprobe_bin):
            err_msg = f"FFprobe executable not found or invalid: {ffprobe_bin}"
            logger.error(f"Transcoding failed for media {media_file_id}: {err_msg}")
            media_file.processing_status = ProcessingStatus.FAILED
            media_file.processing_error = err_msg
            media_file.save(update_fields=['processing_status', 'processing_error'])
            return media_file

        acad_str = str(media_file.academy_uuid) if media_file.academy_uuid else 'global'
        hls_dir_rel = f"academies/{acad_str}/videos/{media_file.id}/hls"
        hls_dir_abs = os.path.join(settings.MEDIA_ROOT, hls_dir_rel)

        try:
            # Probe metadata using strict FFprobe
            meta = cls.probe_video_metadata(source_path)
            media_file.width = meta['width']
            media_file.height = meta['height']
            media_file.duration_seconds = meta['duration_seconds']
            media_file.source_size_bytes = media_file.size_bytes or os.path.getsize(source_path)
            media_file.save(update_fields=['width', 'height', 'duration_seconds', 'source_size_bytes'])

            source_w = meta['width']
            source_h = meta['height']
            is_portrait = source_h > source_w
            aspect_ratio = float(source_w) / float(source_h)

            # Select target profiles (<= min(source_width, source_height) to prevent upscaling)
            profiles = cls.get_supported_profiles(source_w, source_h)

            os.makedirs(hls_dir_abs, exist_ok=True)

            # Clear stale renditions for this media file before starting
            VideoRendition.objects.filter(media_file=media_file).delete()

            master_m3u8_path = os.path.join(hls_dir_abs, "master.m3u8")
            master_entries = []
            total_hls_bytes = 0
            created_renditions = []

            BITRATE_CONFIGS = {
                1080: {"v_bitrate": "5000k", "maxrate": "5350k", "bufsize": "7500k"},
                720:  {"v_bitrate": "2800k", "maxrate": "2996k", "bufsize": "4200k"},
                480:  {"v_bitrate": "1400k", "maxrate": "1498k", "bufsize": "2100k"},
                360:  {"v_bitrate": "800k",  "maxrate": "856k",  "bufsize": "1200k"},
            }

            profile_count = len(profiles)
            for idx, prof in enumerate(profiles, start=1):
                quality_dir_abs = os.path.join(hls_dir_abs, prof.quality_label)
                os.makedirs(quality_dir_abs, exist_ok=True)
                playlist_path_abs = os.path.join(quality_dir_abs, "index.m3u8")
                segment_pattern = os.path.join(quality_dir_abs, "segment_%05d.ts")

                if not is_portrait:
                    target_h = prof.height
                    target_w = int(round(prof.height * aspect_ratio / 2.0) * 2)
                else:
                    target_w = prof.height
                    target_h = int(round(prof.height / aspect_ratio / 2.0) * 2)

                scale_filter = f"scale={target_w}:{target_h}"
                resolution_str = f"{target_w}x{target_h}"

                cfg = BITRATE_CONFIGS.get(prof.height, {
                    "v_bitrate": f"{prof.video_bitrate_kbps}k",
                    "maxrate": f"{int(prof.video_bitrate_kbps * 1.15)}k",
                    "bufsize": f"{int(prof.video_bitrate_kbps * 1.8)}k"
                })

                audio_args = []
                if meta.get('audio_codec'):
                    audio_args = [
                        '-map', '0:a:0?',
                        '-c:a', 'aac',
                        '-b:a', '128k',
                        '-ar', '48000'
                    ]
                else:
                    audio_args = ['-an']

                ffmpeg_cmd = [
                    ffmpeg_bin, '-y', '-i', source_path,
                    '-map', '0:v:0',
                    *audio_args,
                    '-vf', scale_filter,
                    '-c:v', 'libx264',
                    '-preset', 'veryfast',
                    '-pix_fmt', 'yuv420p',
                    '-g', '120',
                    '-keyint_min', '120',
                    '-sc_threshold', '0',
                    '-b:v', cfg["v_bitrate"],
                    '-maxrate', cfg["maxrate"],
                    '-bufsize', cfg["bufsize"],
                    '-hls_time', '4',
                    '-hls_playlist_type', 'vod',
                    '-hls_flags', 'independent_segments',
                    '-hls_segment_type', 'mpegts',
                    '-hls_segment_filename', segment_pattern,
                    playlist_path_abs
                ]

                res = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
                if res.returncode != 0:
                    err_stderr = res.stderr[-8000:] if res.stderr else "Unknown error"
                    logger.error("FFmpeg failed media=%s profile=%s stderr=%s", media_file.id, prof.quality_label, err_stderr)
                    raise RuntimeError(f"FFmpeg transcoding failed for profile '{prof.quality_label}'")

                # Validate generated HLS outputs
                if not os.path.isfile(playlist_path_abs) or os.path.getsize(playlist_path_abs) == 0:
                    raise RuntimeError(f"Playlist m3u8 was not generated or empty for profile '{prof.quality_label}'.")

                segments = sorted(
                    os.path.join(quality_dir_abs, name)
                    for name in os.listdir(quality_dir_abs)
                    if name.endswith('.ts')
                )

                if not segments:
                    raise RuntimeError(f"No HLS segments generated for profile '{prof.quality_label}'.")

                # Probe first segment with strict ffprobe to verify MPEG-TS / H.264
                cls.validate_hls_segment(segments[0])

                # Calculate rendition bytes
                rendition_bytes = sum(os.path.getsize(os.path.join(quality_dir_abs, f)) for f in os.listdir(quality_dir_abs) if os.path.isfile(os.path.join(quality_dir_abs, f)))
                total_hls_bytes += rendition_bytes

                playlist_key_rel = f"{hls_dir_rel}/{prof.quality_label}/index.m3u8"
                rendition, _ = VideoRendition.objects.update_or_create(
                    media_file=media_file,
                    quality_label=prof.quality_label,
                    defaults={
                        'width': target_w,
                        'height': target_h,
                        'video_bitrate_kbps': int(cfg["v_bitrate"].rstrip('k')),
                        'audio_bitrate_kbps': 128 if meta.get('audio_codec') else 0,
                        'playlist_key': playlist_key_rel,
                        'size_bytes': rendition_bytes,
                        'status': 'READY'
                    }
                )
                created_renditions.append(rendition)

                v_bps = int(cfg["v_bitrate"].rstrip('k')) * 1000
                a_bps = 128000 if meta.get('audio_codec') else 0
                bandwidth_bps = v_bps + a_bps

                master_entries.append(
                    f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth_bps},RESOLUTION={resolution_str}\n{prof.quality_label}/index.m3u8"
                )

                progress_pct = 10 + int((idx / profile_count) * 80)
                media_file.processing_progress = progress_pct
                media_file.save(update_fields=['processing_progress'])

            if not created_renditions:
                raise RuntimeError("No valid HLS renditions were generated.")

            # Write master.m3u8
            master_content = "#EXTM3U\n#EXT-X-VERSION:3\n" + "\n".join(master_entries) + "\n"
            with open(master_m3u8_path, "w", encoding="utf-8") as f:
                f.write(master_content)

            master_size = os.path.getsize(master_m3u8_path)
            if master_size == 0 or "#EXTM3U" not in master_content or "#EXT-X-STREAM-INF" not in master_content:
                raise RuntimeError("Generated master.m3u8 is invalid or empty.")

            total_hls_bytes += master_size
            master_key_rel = f"{hls_dir_rel}/master.m3u8"

            # Record storage delta for generated HLS streaming files
            if total_hls_bytes > 0:
                StorageMeteringService.record_upload(
                    media_file=media_file,
                    user=None,
                    event_type=UsageEventType.STREAMING_GENERATED,
                    delta_bytes=total_hls_bytes
                )

            # Finalize MediaFile state to READY
            media_file.stream_manifest_key = master_key_rel
            media_file.streaming_size_bytes = total_hls_bytes
            media_file.processing_status = ProcessingStatus.READY
            media_file.processing_progress = 100
            media_file.processing_error = ''
            media_file.processed_at = timezone.now()
            media_file.save(update_fields=[
                'stream_manifest_key', 'streaming_size_bytes', 'processing_status',
                'processing_progress', 'processing_error', 'processed_at'
            ])

            logger.info(f"Real FFmpeg transcoding completed for '{media_file.original_filename}': {len(created_renditions)} renditions, {total_hls_bytes} streaming bytes.")
            return media_file

        except Exception as err:
            logger.error(f"Failed to transcode video '{media_file.original_filename}': {err}", exc_info=True)
            # Clean partial HLS output directory & stale renditions
            shutil.rmtree(hls_dir_abs, ignore_errors=True)
            VideoRendition.objects.filter(media_file=media_file).delete()

            media_file.stream_manifest_key = ''
            media_file.processing_status = ProcessingStatus.FAILED
            media_file.processing_progress = 0
            media_file.processing_error = str(err)
            media_file.save(update_fields=['stream_manifest_key', 'processing_status', 'processing_progress', 'processing_error'])
            return media_file

    @classmethod
    def reprocess_broken_hls_media(cls) -> int:
        """
        Identifies MediaFiles that failed or have invalid synthetic HLS output and re-enqueues them for real FFmpeg transcoding via Celery.
        """
        from storage.tasks import process_video_transcoding_task
        reprocessed_count = 0
        qs = MediaFile.objects.filter(media_type='VIDEO')
        for mf in qs:
            needs_reprocess = False
            if mf.processing_status in [ProcessingStatus.FAILED, ProcessingStatus.PROCESSING, ProcessingStatus.QUEUED, ProcessingStatus.UPLOADED]:
                needs_reprocess = True
            elif mf.processing_status == ProcessingStatus.READY:
                if not mf.stream_manifest_key:
                    needs_reprocess = True
                else:
                    master_abs = os.path.join(settings.MEDIA_ROOT, mf.stream_manifest_key)
                    if not os.path.exists(master_abs):
                        needs_reprocess = True
                    else:
                        hls_dir = os.path.dirname(master_abs)
                        segments = glob.glob(os.path.join(hls_dir, "*", "*.ts"))
                        if not segments:
                            needs_reprocess = True
                        else:
                            # Check if master has only 1 rendition when source is 720p+
                            try:
                                with open(master_abs, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                entries_count = content.count('#EXT-X-STREAM-INF')
                                if entries_count <= 1 and min(mf.width or 0, mf.height or 0) >= 480:
                                    needs_reprocess = True
                            except Exception:
                                needs_reprocess = True

            if needs_reprocess and mf.storage_path and os.path.exists(mf.storage_path):
                logger.info(f"Re-enqueuing MediaFile {mf.id} for multi-quality FFmpeg transcoding.")
                hls_dir = os.path.join(settings.MEDIA_ROOT, f"academies/{mf.academy_uuid or 'global'}/videos/{mf.id}/hls")
                shutil.rmtree(hls_dir, ignore_errors=True)
                VideoRendition.objects.filter(media_file=mf).delete()

                mf.stream_manifest_key = ''
                mf.processing_status = ProcessingStatus.QUEUED
                mf.processing_progress = 0
                mf.processing_error = ''
                mf.save(update_fields=['stream_manifest_key', 'processing_status', 'processing_progress', 'processing_error'])

                try:
                    process_video_transcoding_task.delay(str(mf.id))
                except Exception as celery_err:
                    logger.warning(f"Celery broker unavailable ({celery_err}). Transcoding synchronously.")
                    cls.process_media_video(mf.id)
                reprocessed_count += 1

        return reprocessed_count

