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


def resolve_reportlab_font(font_key_or_family: str, font_weight: str = 'normal', academy=None) -> str:
    """
    Resolves a font key or family name to a ReportLab font name.
    Registers TTF font files if available in CertificateFont registry.
    """
    if not font_key_or_family:
        return 'Helvetica-Bold' if 'bold' in str(font_weight).lower() else 'Helvetica'

    font_key = str(font_key_or_family).strip()
    is_bold = 'bold' in str(font_weight).lower() or str(font_weight) in ['700', '800', '900']

    try:
        from django.db.models import Q
        from certificates.models import CertificateFont, FontSourceChoices

        query = CertificateFont.objects.filter(is_active=True)
        if academy:
            query = query.filter(Q(source=FontSourceChoices.SYSTEM) | Q(academy=academy, source=FontSourceChoices.ACADEMY))
        else:
            query = query.filter(source=FontSourceChoices.SYSTEM)

        font_obj = query.filter(key=font_key).first()
        if not font_obj:
            font_obj = query.filter(family__iexact=font_key).first()

        if font_obj and font_obj.media_file:
            media = font_obj.media_file
            candidate_path = getattr(media, 'storage_path', '') or getattr(media, 'relative_path', '') or font_obj.file_url
            if candidate_path:
                if os.path.isabs(candidate_path) and os.path.exists(candidate_path):
                    abs_path = candidate_path
                else:
                    abs_path = os.path.join(settings.MEDIA_ROOT, candidate_path.lstrip('/'))

                if os.path.exists(abs_path):
                    registered_name = f"{font_obj.key}_{font_weight}"
                    try:
                        from reportlab.pdfbase import pdfmetrics
                        from reportlab.pdfbase.ttfonts import TTFont
                        pdfmetrics.registerFont(TTFont(registered_name, abs_path))
                        return registered_name
                    except Exception:
                        pass
    except Exception:
        pass

    fam_lower = font_key.lower()
    if 'serif' in fam_lower or 'playfair' in fam_lower or 'merriweather' in fam_lower or 'cinzel' in fam_lower:
        return 'Times-Bold' if is_bold else 'Times-Roman'
    elif 'mono' in fam_lower or 'code' in fam_lower:
        return 'Courier-Bold' if is_bold else 'Courier'

    return 'Helvetica-Bold' if is_bold else 'Helvetica'

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
        page_width, page_height = resolve_page_size(
            page_size=page_size,
            custom_width=custom_width,
            custom_height=custom_height,
            custom_unit=custom_unit,
            orientation=orientation
        )

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

        # 1. Draw Background Media
        cls._draw_background(c, background_media, page_width, page_height)

        # 2. Draw Student Photo if enabled
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

        # 3. Draw Elements (Freeform Array or Structured Layout Object)
        cls._draw_elements(
            c,
            snapshot_data,
            template_data,
            page_width,
            page_height
        )

        # 4. Draw QR Code if verification_url provided
        if verification_url:
            qr_cfg = template_data.get('qr_code', {
                'x': page_width - 110,
                'y': 40,
                'width': 70,
                'height': 70
            })
            cls._draw_qr_code(c, verification_url, qr_cfg, page_width, page_height)

        c.showPage()
        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    @classmethod
    def _resolve_media_path(cls, media_file):
        if not media_file:
            return None
        if isinstance(media_file, str):
            if os.path.isabs(media_file) and os.path.exists(media_file):
                return media_file
            rel_path = media_file.lstrip('/')
            abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
            return abs_path if os.path.exists(abs_path) else None

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
    def _draw_elements(cls, c, snapshot_data, template_data, page_width, page_height):
        elements_list = []
        if isinstance(template_data, dict):
            elements_list = template_data.get('elements', [])

        if not elements_list and isinstance(template_data, list):
            elements_list = template_data

        # Fallback default elements if empty
        if not elements_list:
            elements_list = [
                {
                    'binding': 'static',
                    'text': 'CERTIFICATE OF COMPLETION',
                    'x': 0.5,
                    'y': 0.8,
                    'width': 0.8,
                    'font_size': 28,
                    'font_weight': 'bold',
                    'text_align': 'center',
                    'color': '#0F172A',
                },
                {
                    'binding': 'student.full_name',
                    'x': 0.5,
                    'y': 0.5,
                    'width': 0.8,
                    'font_size': 32,
                    'font_weight': 'bold',
                    'text_align': 'center',
                    'color': '#2563EB',
                },
                {
                    'binding': 'course.title',
                    'x': 0.5,
                    'y': 0.35,
                    'width': 0.8,
                    'font_size': 20,
                    'font_weight': 'bold',
                    'text_align': 'center',
                    'color': '#0F172A',
                },
                {
                    'binding': 'certificate.number',
                    'x': 0.85,
                    'y': 0.1,
                    'width': 0.3,
                    'font_size': 11,
                    'text_align': 'right',
                    'color': '#64748B',
                    'prefix': 'No: ',
                },
                {
                    'binding': 'certificate.issue_date',
                    'x': 0.15,
                    'y': 0.1,
                    'width': 0.3,
                    'font_size': 11,
                    'text_align': 'left',
                    'color': '#64748B',
                    'prefix': 'Date: ',
                },
            ]

        for item in elements_list:
            if not isinstance(item, dict):
                continue

            binding = item.get('binding') or item.get('field', '')
            text_value = item.get('text', '')
            prefix = item.get('prefix', '')
            suffix = item.get('suffix', '')

            if binding and binding != 'static':
                val = snapshot_data.get(binding, '')
                text_value = f"{prefix}{val}{suffix}".strip() if val != '' else ''
            elif text_value:
                # Interpolate placeholders e.g. {{student.full_name}}
                for k, v in snapshot_data.items():
                    if isinstance(text_value, str) and f"{{{{{k}}}}}" in text_value:
                        text_value = text_value.replace(f"{{{{{k}}}}}", str(v))
                text_value = f"{prefix}{text_value}{suffix}".strip()

            if not text_value:
                continue

            # Position parsing (Support ratio 0..1 or absolute pt coordinates)
            raw_x = item.get('x', 0.5)
            raw_y = item.get('y', 0.5)
            raw_width = item.get('width', 0.8)

            x = float(raw_x) * page_width if isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1 else float(raw_x)
            # In ReportLab, Y is 0 at bottom. Convert from top-left designer coordinate if ratio
            y = (1.0 - float(raw_y)) * page_height if isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1 else float(raw_y)
            container_width = float(raw_width) * page_width if isinstance(raw_width, (int, float)) and 0 <= raw_width <= 1 else float(raw_width)
            raw_height = item.get('height', 0.08)
            container_height = float(raw_height) * page_height if isinstance(raw_height, (int, float)) and 0 <= raw_height <= 1 else float(raw_height)

            base_max = item.get('font_size') or item.get('fontSize') or item.get('max_font_size') or item.get('maxFontSize')
            configured_max = float(base_max) if base_max is not None else 32.0
            configured_min = item.get('min_font_size') or item.get('minFontSize')
            min_font_size = float(configured_min) if configured_min is not None else 1.0
            auto_fit = item.get('auto_fit', item.get('autoFit', True))

            padding_cfg = item.get('padding') or {}
            pad_l = float(padding_cfg.get('left', 2)) if isinstance(padding_cfg, dict) else 2.0
            pad_r = float(padding_cfg.get('right', 2)) if isinstance(padding_cfg, dict) else 2.0
            pad_t = float(padding_cfg.get('top', 1)) if isinstance(padding_cfg, dict) else 1.0
            pad_b = float(padding_cfg.get('bottom', 1)) if isinstance(padding_cfg, dict) else 1.0

            avail_width = max(1.0, container_width - (pad_l + pad_r))
            avail_height = max(1.0, container_height - (pad_t + pad_b))

            font_weight = str(item.get('font_weight', item.get('fontWeight', 'normal'))).lower()
            raw_font = item.get('fontKey') or item.get('font_key') or item.get('fontFamily') or item.get('font_family', 'Inter')

            academy_id = snapshot_data.get('academy_id') if isinstance(snapshot_data, dict) else None
            academy_obj = None
            if academy_id:
                from academy.models import Academy
                try:
                    academy_obj = Academy.objects.filter(id=academy_id).first()
                except Exception:
                    pass

            font_name = resolve_reportlab_font(raw_font, font_weight, academy=academy_obj)

            color_hex = str(item.get('color', '#000000'))
            align = str(item.get('text_align', item.get('textAlign', 'center'))).lower()

            # --- AUTOMATIC FONT FIT CALCULATOR (Width + Height scaling up to configured_max) ---
            fitted_font_size = configured_max
            if auto_fit and avail_width > 0 and avail_height > 0:
                cur_size = configured_max
                while cur_size >= min_font_size:
                    string_w = c.stringWidth(text_value, font_name, cur_size)
                    string_h = cur_size * 1.0
                    if string_w <= avail_width and string_h <= avail_height:
                        fitted_font_size = cur_size
                        break
                    cur_size -= 0.5
                else:
                    fitted_font_size = min_font_size

            c.saveState()

            # Clip region to exact container bounds as hard safety guard
            clip_x = x - (container_width / 2.0) if (isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1) else x
            clip_y = y - (container_height / 2.0) if (isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1) else y
            clip_path = c.beginPath()
            clip_path.rect(clip_x, clip_y, container_width, container_height)
            c.clipPath(clip_path, stroke=0, fill=0)

            try:
                c.setFont(font_name, fitted_font_size)
            except Exception:
                c.setFont('Helvetica', fitted_font_size)

            try:
                c.setFillColor(HexColor(color_hex))
            except Exception:
                c.setFillColorRGB(0, 0, 0)

            if align == 'center':
                c.drawCentredString(x, y, text_value)
            elif align == 'right':
                c.drawRightString(x, y, text_value)
            else:
                left_x = clip_x + pad_l
                c.drawString(left_x, y, text_value)

            c.restoreState()

    @classmethod
    def _draw_qr_code(cls, c, url, cfg, page_width, page_height):
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

            raw_x = cfg.get('x', 0.85)
            raw_y = cfg.get('y', 0.15)
            raw_w = cfg.get('width', 0.1)

            x = float(raw_x) * page_width if isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1 else float(raw_x)
            y = (1.0 - float(raw_y)) * page_height if isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1 else float(raw_y)
            width = float(raw_w) * page_width if isinstance(raw_w, (int, float)) and 0 <= raw_w <= 1 else float(raw_w)

            c.drawImage(image_reader, x, y, width=width, height=width)
        except Exception:
            pass
