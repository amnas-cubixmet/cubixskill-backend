import os

from django.conf import settings
from django.db import migrations


def repair_font_formats(apps, schema_editor):
    CertificateFont = apps.get_model('certificates', 'CertificateFont')
    for font in CertificateFont.objects.select_related('media_file').all():
        candidate_path = ''
        if font.media_file:
            candidate_path = getattr(font.media_file, 'storage_path', '') or getattr(font.media_file, 'relative_path', '') or getattr(font.media_file, 'storage_key', '')
        if not candidate_path:
            candidate_path = font.file_url or ''

        if candidate_path:
            clean_rel = candidate_path.lstrip('/')
            clean_rel = clean_rel.removeprefix('media/')
            abs_path = os.path.join(settings.MEDIA_ROOT, clean_rel)
            if os.path.exists(abs_path):
                ext = abs_path.split('.')[-1].upper()
                if ext in ['TTF', 'OTF', 'WOFF', 'WOFF2'] and font.format != ext:
                    font.format = ext
                    font.save(update_fields=['format'])

def reverse_repair(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('certificates', '0007_certificatefont_format_certificatefont_size_bytes_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_font_formats, reverse_repair),
    ]
