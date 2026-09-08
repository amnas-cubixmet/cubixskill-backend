import logging
import os

from certificates.font_validator import CertificateFontValidator
from certificates.models import CertificateFont
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Revalidates all stored CertificateFont records for PDF engine compatibility, outline types, and formats."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting CertificateFont revalidation..."))
        fonts = CertificateFont.objects.select_related('media_file').all()

        total = fonts.count()
        valid_count = 0
        unsupported_count = 0
        missing_count = 0
        updated_metadata_count = 0

        for font in fonts:
            candidate_path = ''
            if font.media_file:
                candidate_path = getattr(font.media_file, 'storage_path', '') or getattr(font.media_file, 'relative_path', '') or getattr(font.media_file, 'storage_key', '')
            if not candidate_path:
                candidate_path = font.file_url or ''

            if not candidate_path:
                self.stdout.write(self.style.WARNING(f"Font '{font.name}' ({font.id}): Missing media file path."))
                missing_count += 1
                font.pdf_compatible = False
                font.save(update_fields=['pdf_compatible'])
                continue

            clean_rel = candidate_path.lstrip('/')
            clean_rel = clean_rel.removeprefix('media/')
            abs_path = os.path.join(settings.MEDIA_ROOT, clean_rel)

            if not os.path.exists(abs_path):
                self.stdout.write(self.style.WARNING(f"Font '{font.name}' ({font.id}): File does not exist at '{abs_path}'."))
                missing_count += 1
                font.pdf_compatible = False
                font.save(update_fields=['pdf_compatible'])
                continue

            res = CertificateFontValidator.inspect_and_validate_font(abs_path, str(font.id))

            update_fields = []
            if font.format != res.format_ext:
                font.format = res.format_ext
                update_fields.append('format')

            if font.outline_type != res.outline_type:
                font.outline_type = res.outline_type
                update_fields.append('outline_type')

            if font.pdf_compatible != res.is_pdf_compatible:
                font.pdf_compatible = res.is_pdf_compatible
                update_fields.append('pdf_compatible')

            if update_fields:
                font.save(update_fields=update_fields)
                updated_metadata_count += 1

            if res.is_pdf_compatible:
                valid_count += 1
                self.stdout.write(self.style.SUCCESS(f"VALID: '{font.name}' ({font.id}) - format: {res.format_ext}, outline: {res.outline_type}"))
            else:
                unsupported_count += 1
                self.stdout.write(self.style.ERROR(f"UNSUPPORTED: '{font.name}' ({font.id}) - outline: {res.outline_type}, reason: {res.error_message}"))

        self.stdout.write(self.style.SUCCESS("\n--- CertificateFont Revalidation Summary ---"))
        self.stdout.write(f"Total fonts evaluated: {total}")
        self.stdout.write(self.style.SUCCESS(f"PDF Compatible: {valid_count}"))
        self.stdout.write(self.style.ERROR(f"PDF Unsupported: {unsupported_count}"))
        self.stdout.write(self.style.WARNING(f"Missing files: {missing_count}"))
        self.stdout.write(f"Updated metadata records: {updated_metadata_count}")
