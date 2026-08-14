import io
import os
import qrcode
from PIL import Image, ImageDraw, ImageOps
from django.conf import settings
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import mm, cm, inch
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

PAGE_SIZES = {
    'A4': A4,
    'LETTER': LETTER,
}

UNIT_MAP = {
    'MM': mm,
    'CM': cm,
    'INCH': inch,
}

def resolve_page_size(
    page_size: str = 'A4',
    custom_width=None,
    custom_height=None,
    custom_unit=None,
    orientation: str = 'LANDSCAPE'
) -> tuple[float, float]:
    """
    Resolves page dimensions in ReportLab points (1/72 inch).
    Supports predefined (A4, LETTER) and custom dimensions (MM, CM, INCH).
    """
    if str(page_size).upper() == 'CUSTOM' and custom_width and custom_height and custom_unit:
        unit = UNIT_MAP.get(str(custom_unit).upper(), mm)
        width_pts = float(custom_width) * unit
        height_pts = float(custom_height) * unit
        size = (width_pts, height_pts)
    else:
        size = PAGE_SIZES.get(str(page_size).upper(), A4)

    if str(orientation).upper() == 'LANDSCAPE':
        return (max(size), min(size))
    else:
        return (min(size), max(size))


# --------------------------------------------------------------
# Certificate PDF Generator
# Certificate PDFs are generated on demand by default to avoid storing
# one persistent PDF per student.
# Custom width/height are converted to ReportLab points before rendering.
# --------------------------------------------------------------

class CertificatePDFGenerator:
    PAGE_SIZES = PAGE_SIZES
    UNIT_MAP = UNIT_MAP

    @classmethod
    def generate_pdf(
        cls,
        snapshot_data: dict,
        template_data: dict,
        orientation: str = 'LANDSCAPE',
        page_size: str = 'A4',
        custom_width=None,
        custom_height=None,
        custom_unit=None,
        background_media=None,
        show_student_photo: bool = False,
        student_photo_shape: str = 'CIRCLE',
        student_photo_media=None,
        verification_url: str = None
    ) -> bytes:
        """
        Generates a PDF certificate in memory as raw bytes.
        """
        # 1. Resolve Page Dimensions
        page_width, page_height = resolve_page_size(
            page_size=page_size,
            custom_width=custom_width,
            custom_height=custom_height,
            custom_unit=custom_unit,
            orientation=orientation
        )

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

        # 2. Draw Background Media if present
        cls._draw_background(c, background_media, page_width, page_height)

        # 3. Draw Student Photo if enabled
        if show_student_photo and student_photo_media:
            photo_cfg = template_data.get('student_photo', {})
            cls._draw_student_photo(
                c,
                student_photo_media,
                photo_cfg,
                student_photo_shape,
                page_width,
                page_height
            )

        # 4. Draw Placeholders & Text Elements
        cls._draw_text_elements(
            c,
            snapshot_data,
            template_data,
            page_width,
            page_height
        )

        # 5. Draw QR Code if verification_url provided
        if verification_url:
            qr_cfg = template_data.get('qr_code', {
                'x': page_width - 110,
                'y': 40,
                'width': 70,
                'height': 70
            })
            cls._draw_qr_code(c, verification_url, qr_cfg)

        c.showPage()
        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    @classmethod
    def _resolve_media_path(cls, media_file):
        """
        Helper to resolve absolute filesystem path of a MediaFile object or str path.
        """
        if not media_file:
            return None
        if isinstance(media_file, str):
            if os.path.isabs(media_file) and os.path.exists(media_file):
                return media_file
            rel_path = media_file.lstrip('/')
            abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
            return abs_path if os.path.exists(abs_path) else None

        # MediaFile Django model
        relative_path = getattr(media_file, 'relative_path', '')
        if relative_path:
            abs_path = os.path.join(settings.MEDIA_ROOT, relative_path.lstrip('/'))
            if os.path.exists(abs_path):
                return abs_path

        stored_filename = getattr(media_file, 'stored_filename', '')
        if stored_filename:
            abs_path = os.path.join(settings.MEDIA_ROOT, stored_filename)
            if os.path.exists(abs_path):
                return abs_path

        return None

    @classmethod
    def _draw_background(cls, c, background_media, page_width, page_height):
        file_path = cls._resolve_media_path(background_media)
        if file_path and os.path.exists(file_path):
            try:
                c.drawImage(file_path, 0, 0, width=page_width, height=page_height, preserveAspectRatio=False)
            except Exception:
                # If image loading fails, fallback cleanly
                pass

    @classmethod
    def _draw_student_photo(cls, c, photo_media, cfg, shape, page_width, page_height):
        file_path = cls._resolve_media_path(photo_media)
        if not file_path or not os.path.exists(file_path):
            return

        x = float(cfg.get('x', 90))
        y = float(cfg.get('y', page_height - 210))
        width = float(cfg.get('width', 120))
        height = float(cfg.get('height', 120))

        try:
            pil_img = Image.open(file_path).convert('RGBA')
            pil_img = ImageOps.fit(pil_img, (int(width * 2), int(height * 2)), Image.Resampling.LANCZOS)

            if shape.upper() == 'CIRCLE':
                mask = Image.new('L', pil_img.size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, pil_img.size[0], pil_img.size[1]), fill=255)
                pil_img.putalpha(mask)

            img_bytes = io.BytesIO()
            pil_img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            image_reader = ImageReader(img_bytes)

            c.drawImage(image_reader, x, y, width=width, height=height, mask='auto')
        except Exception:
            pass

    @classmethod
    def _draw_text_elements(cls, c, snapshot_data, template_data, page_width, page_height):
        default_layout = {
            'academy_name': {
                'x': page_width / 2,
                'y': page_height - 90,
                'font_name': 'Helvetica-Bold',
                'font_size': 20,
                'color': '#334155',
                'align': 'center'
            },
            'title': {
                'x': page_width / 2,
                'y': page_height - 140,
                'font_name': 'Helvetica-Bold',
                'font_size': 32,
                'color': '#0F172A',
                'align': 'center',
                'text': 'CERTIFICATE OF COMPLETION'
            },
            'sub_title': {
                'x': page_width / 2,
                'y': page_height - 180,
                'font_name': 'Helvetica',
                'font_size': 14,
                'color': '#64748B',
                'align': 'center',
                'text': 'This is proudly presented to'
            },
            'student_name': {
                'x': page_width / 2,
                'y': page_height - 240,
                'font_name': 'Helvetica-Bold',
                'font_size': 30,
                'color': '#1E3A8A',
                'align': 'center'
            },
            'course_intro': {
                'x': page_width / 2,
                'y': page_height - 280,
                'font_name': 'Helvetica',
                'font_size': 14,
                'color': '#64748B',
                'align': 'center',
                'text': 'for successfully completing the course'
            },
            'course_name': {
                'x': page_width / 2,
                'y': page_height - 325,
                'font_name': 'Helvetica-Bold',
                'font_size': 22,
                'color': '#0F172A',
                'align': 'center'
            },
            'issue_date': {
                'x': 100,
                'y': 60,
                'font_name': 'Helvetica',
                'font_size': 11,
                'color': '#475569',
                'align': 'left'
            },
            'certificate_number': {
                'x': page_width / 2,
                'y': 60,
                'font_name': 'Helvetica-Bold',
                'font_size': 11,
                'color': '#475569',
                'align': 'center'
            }
        }

        # Merge template_data layout over defaults
        merged_layout = dict(default_layout)
        if isinstance(template_data, dict):
            for k, v in template_data.items():
                if isinstance(v, dict) and k not in ['student_photo', 'qr_code']:
                    if k in merged_layout:
                        merged_layout[k] = {**merged_layout[k], **v}
                    else:
                        merged_layout[k] = v

        for field_key, item in merged_layout.items():
            if not isinstance(item, dict):
                continue

            text_value = item.get('text')
            if not text_value:
                text_value = snapshot_data.get(field_key, '')

            # Interpolate any embedded placeholders {{placeholder}}
            if isinstance(text_value, str) and '{{' in text_value:
                for k, val in snapshot_data.items():
                    text_value = text_value.replace(f'{{{{{k}}}}}', str(val))

            if not text_value:
                continue

            x = float(item.get('x', page_width / 2))
            y = float(item.get('y', page_height / 2))
            font_name = str(item.get('font_name', 'Helvetica'))
            font_size = float(item.get('font_size', 14))
            color_hex = str(item.get('color', '#000000'))
            align = str(item.get('align', 'center')).lower()

            c.saveState()
            try:
                c.setFont(font_name, font_size)
            except Exception:
                c.setFont('Helvetica', font_size)

            try:
                c.setFillColor(HexColor(color_hex))
            except Exception:
                c.setFillColorRGB(0, 0, 0)

            if align == 'center':
                c.drawCentredString(x, y, text_value)
            elif align == 'right':
                c.drawRightString(x, y, text_value)
            else:
                c.drawString(x, y, text_value)

            c.restoreState()

    @classmethod
    def _draw_qr_code(cls, c, url, cfg):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            img_bytes = io.BytesIO()
            img.save(img_bytes)
            img_bytes.seek(0)
            image_reader = ImageReader(img_bytes)

            x = float(cfg.get('x', 700))
            y = float(cfg.get('y', 40))
            width = float(cfg.get('width', 70))
            height = float(cfg.get('height', 70))

            c.drawImage(image_reader, x, y, width=width, height=height)
        except Exception:
            pass
