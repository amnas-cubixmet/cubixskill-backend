import io
import os
import logging
import qrcode
from PIL import Image, ImageDraw, ImageOps

logger = logging.getLogger(__name__)
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


def convert_otf_cff_to_ttf(abs_otf_path: str) -> str:
    """
    Converts OpenType font with CFF outlines (OTTO / CFF) to TrueType quadratic curves
    and writes it to a converted cache file in settings.MEDIA_ROOT / 'font_cache'.
    Returns the path to the converted TTF file, or abs_otf_path if conversion is not required.
    """
    if not abs_otf_path or not os.path.exists(abs_otf_path):
        return abs_otf_path

    ext = abs_otf_path.split('.')[-1].lower()
    if ext not in ['otf', 'cff']:
        return abs_otf_path

    try:
        from fontTools.ttLib import TTFont as FTFont
        otf = FTFont(abs_otf_path)
        is_cff = 'CFF ' in otf or otf.sfntVersion == 'OTTO'
        otf.close()
        if not is_cff:
            return abs_otf_path
    except Exception as e:
        logger.warning(f"Could not inspect font file '{abs_otf_path}' with fontTools: {e}")
        return abs_otf_path

    cache_dir = os.path.join(settings.MEDIA_ROOT, 'font_cache')
    os.makedirs(cache_dir, exist_ok=True)
    basename = os.path.basename(abs_otf_path).rsplit('.', 1)[0]
    out_ttf_path = os.path.join(cache_dir, f"{basename}_converted.ttf")

    if os.path.exists(out_ttf_path):
        return out_ttf_path

    try:
        from fontTools.ttLib import TTFont as FTFont
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.pens.cu2quPen import Cu2QuPen
        from fontTools.ttLib.tables._g_l_y_f import table__g_l_y_f
        from fontTools.ttLib.tables._l_o_c_a import table__l_o_c_a
        from fontTools.ttLib.tables._m_a_x_p import table__m_a_x_p

        otf = FTFont(abs_otf_path)
        glyph_set = otf.getGlyphSet()
        glyphs = {}
        for name in otf.getGlyphOrder():
            pen = TTGlyphPen(glyph_set)
            cuPen = Cu2QuPen(pen, max_err=1.0)
            glyph_set[name].draw(cuPen)
            glyphs[name] = pen.glyph()

        ttf = FTFont()
        ttf.sfntVersion = '\x00\x01\x00\x00'
        for table in ['head', 'hhea', 'OS/2', 'name', 'cmap', 'post', 'hmtx']:
            if table in otf:
                ttf[table] = otf[table]

        ttf['glyf'] = table__g_l_y_f()
        ttf['glyf'].glyphs = glyphs
        ttf['loca'] = table__l_o_c_a()
        ttf.setGlyphOrder(otf.getGlyphOrder())

        maxp = table__m_a_x_p()
        maxp.tableVersion = 0x00010000
        maxp.numGlyphs = len(glyphs)
        maxp.maxPoints = 0
        maxp.maxContours = 0
        maxp.maxCompositePoints = 0
        maxp.maxCompositeContours = 0
        maxp.maxZones = 2
        maxp.maxTwilightPoints = 0
        maxp.maxStorage = 0
        maxp.maxFunctionDefs = 0
        maxp.maxInstructionDefs = 0
        maxp.maxStackElements = 0
        maxp.maxSizeOfInstructions = 0
        maxp.maxComponentElements = 0
        maxp.maxComponentDepth = 0
        ttf['maxp'] = maxp

        tmp_path = out_ttf_path + ".tmp"
        ttf.save(tmp_path)
        otf.close()
        ttf.close()

        if os.path.exists(out_ttf_path):
            os.remove(tmp_path)
        else:
            os.rename(tmp_path, out_ttf_path)

        return out_ttf_path
    except Exception as conv_err:
        logger.error(f"Failed to convert OTF/CFF font '{abs_otf_path}' to TTF: {conv_err}")
        return abs_otf_path


def resolve_reportlab_font(font_key_or_family: str, font_weight: str = 'normal', academy=None) -> str:
    """
    Resolves fontId, UUID, fontKey or font family name (including 'cubix-font-<uuid>') to a ReportLab font.
    Registers stored TTF/OTF font files from CertificateFont model.
    Raises rest_framework ValidationError CERTIFICATE_FONT_NOT_AVAILABLE if custom font file cannot be loaded/registered.
    """
    if not font_key_or_family:
        return 'Helvetica-Bold' if 'bold' in str(font_weight).lower() else 'Helvetica'

    font_key = str(font_key_or_family).strip()
    is_bold = 'bold' in str(font_weight).lower() or str(font_weight) in ['700', '800', '900']

    # Extract target UUID if present
    target_uuid = None
    if font_key.startswith('cubix-font-'):
        target_uuid = font_key.replace('cubix-font-', '').strip()
    elif len(font_key) == 36 and '-' in font_key:
        target_uuid = font_key

    from django.db.models import Q
    from certificates.models import CertificateFont, FontSourceChoices
    from rest_framework.exceptions import ValidationError

    font_obj = None

    # Academy-safe tenant lookup: if academy is provided, match tenant-safe font or system font
    academy_filter = Q(academy=academy) if academy else Q()

    if target_uuid:
        try:
            query = Q(id=target_uuid)
            if academy:
                query &= (Q(source=FontSourceChoices.SYSTEM) | Q(academy=academy, source=FontSourceChoices.ACADEMY))
            font_obj = CertificateFont.objects.filter(query).first()
        except Exception:
            pass

    if not font_obj:
        query = Q(key=font_key)
        if academy:
            query &= (Q(source=FontSourceChoices.SYSTEM) | Q(academy=academy, source=FontSourceChoices.ACADEMY))
        font_obj = CertificateFont.objects.filter(query).first()

    if not font_obj and not target_uuid:
        query = Q(family__iexact=font_key)
        if academy:
            query &= (Q(source=FontSourceChoices.SYSTEM) | Q(academy=academy, source=FontSourceChoices.ACADEMY))
        font_obj = CertificateFont.objects.filter(query).first()

    if font_obj:
        if font_obj.source == FontSourceChoices.ACADEMY:
            # Enforce tenant match if academy is supplied
            if academy and font_obj.academy_id and font_obj.academy_id != academy.id:
                logger.warning(f"Certificate custom font '{font_obj.name}' (UUID: {font_obj.id}) does not belong to academy {academy.id}. Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            if not font_obj.is_active:
                logger.warning(f"Certificate custom font '{font_obj.name}' (UUID: {font_obj.id}) is deactivated. Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            if not font_obj.media_file:
                logger.warning(f"Media file reference missing for custom font '{font_obj.name}' (UUID: {font_obj.id}). Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            media = font_obj.media_file
            candidate_path = getattr(media, 'storage_path', '') or getattr(media, 'relative_path', '') or getattr(media, 'storage_key', '') or font_obj.file_url
            abs_path = None
            if candidate_path:
                if os.path.isabs(candidate_path) and os.path.exists(candidate_path):
                    abs_path = candidate_path
                else:
                    clean_rel = candidate_path.lstrip('/')
                    if clean_rel.startswith('media/'):
                        clean_rel = clean_rel[6:]
                    abs_path = os.path.join(settings.MEDIA_ROOT, clean_rel)

            if not abs_path or not os.path.exists(abs_path):
                logger.warning(f"Font file for '{font_obj.name}' (UUID: {font_obj.id}) could not be resolved on storage at path {abs_path}. Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            # 1. Resolve storage file path
            usable_font_path = abs_path
            ext = font_obj.format.upper() if font_obj.format else (abs_path.split('.')[-1].upper() if '.' in abs_path else '')

            if ext in ['WOFF', 'WOFF2']:
                logger.warning(f"Font format '{ext}' for font '{font_obj.name}' (UUID: {font_obj.id}) is browser-only. Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            # 2. OTF/CFF Conversion Flow: Convert CFF outlines to TrueType curves if needed
            if ext in ['OTF', 'CFF'] or abs_path.lower().endswith('.otf'):
                logger.info(f"Checking OTF/CFF conversion requirement for font '{font_obj.name}' (UUID: {font_obj.id}) at '{abs_path}'")
                usable_font_path = convert_otf_cff_to_ttf(abs_path)
                logger.info(f"Usable font path after conversion check for font '{font_obj.name}' (UUID: {font_obj.id}): '{usable_font_path}'")

            if not usable_font_path or not os.path.exists(usable_font_path):
                logger.warning(f"Certificate font conversion/file resolution failed for font '{font_obj.name}' (UUID: {font_obj.id}). Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            # 3. Perform CertificateFontValidator check ON THE CONVERTED/USABLE FONT
            from certificates.font_validator import CertificateFontValidator
            val_res = CertificateFontValidator.inspect_and_validate_font(usable_font_path, str(font_obj.id))

            if not val_res.is_pdf_compatible:
                logger.warning(
                    f"Certificate font fallback used for field/template: Custom font '{font_obj.name}' (UUID: {font_obj.id}) is not PDF-compatible ({val_res.error_message}). Using safe PDF fallback font."
                )
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

            # 4. Register converted font with exact runtime family name cubix-font-<uuid>
            registered_name = f"cubix-font-{str(font_obj.id)}"
            logger.info(f"Certificate font resolved: uuid={font_obj.id}, format={ext}, runtime={registered_name}, usable_path={usable_font_path}")
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                if registered_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(registered_name, usable_font_path))
                return registered_name
            except Exception as reg_err:
                logger.warning(f"Failed to register ReportLab font '{registered_name}' from path '{usable_font_path}': {reg_err}. Falling back to default font.")
                return 'Helvetica-Bold' if is_bold else 'Helvetica'

    if target_uuid:
        logger.warning(f"Custom certificate font with UUID '{target_uuid}' was not found in font database for academy {academy}. Falling back to default font.")
        return 'Helvetica-Bold' if is_bold else 'Helvetica'

    fam_lower = font_key.lower()
    if 'serif' in fam_lower or 'playfair' in fam_lower or 'merriweather' in fam_lower or 'cinzel' in fam_lower:
        return 'Times-Bold' if is_bold else 'Times-Roman'
    elif 'mono' in fam_lower or 'code' in fam_lower:
        return 'Courier-Bold' if is_bold else 'Courier'

    return 'Helvetica-Bold' if is_bold else 'Helvetica'


def calculate_background_rect(
    image_width: float,
    image_height: float,
    page_width: float,
    page_height: float,
    fit: str = 'cover',
    position: str = 'center'
) -> tuple[float, float, float, float]:
    """
    Calculates drawing rectangle (x, y, draw_width, draw_height) for certificate background image.
    ReportLab Y-axis origin (0, 0) is at bottom-left corner.
    """
    if not image_width or not image_height or not page_width or not page_height:
        return (0.0, 0.0, float(page_width), float(page_height))

    fit_mode = str(fit).lower().strip() if fit else 'cover'
    pos_mode = str(position).lower().strip().replace(' ', '-').replace('_', '-') if position else 'center'

    if fit_mode in ['fill', 'stretch']:
        return (0.0, 0.0, float(page_width), float(page_height))

    if fit_mode == 'cover':
        scale = max(page_width / image_width, page_height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale
    elif fit_mode == 'contain':
        scale = min(page_width / image_width, page_height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale
    elif fit_mode in ['original', 'center']:
        draw_width = float(image_width)
        draw_height = float(image_height)
    else:  # fallback cover
        scale = max(page_width / image_width, page_height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale

    remaining_width = page_width - draw_width
    remaining_height = page_height - draw_height

    # Horizontal position (x)
    if pos_mode in ['top-left', 'left', 'bottom-left']:
        x = 0.0
    elif pos_mode in ['top-right', 'right', 'bottom-right']:
        x = remaining_width
    else:  # 'center', 'top', 'bottom'
        x = remaining_width / 2.0

    # Vertical position (y) in ReportLab: 0 is BOTTOM, page_height is TOP
    if pos_mode in ['top', 'top-left', 'top-right']:
        y = remaining_height
    elif pos_mode in ['bottom', 'bottom-left', 'bottom-right']:
        y = 0.0
    else:  # 'center', 'left', 'right'
        y = remaining_height / 2.0

    return (x, y, draw_width, draw_height)


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
        bg_config = {}
        if isinstance(template_data, dict):
            bg_config = template_data.get('background', {})
            if not isinstance(bg_config, dict):
                bg_config = {}
            if 'fit' not in bg_config:
                bg_config['fit'] = template_data.get('bgFit') or template_data.get('bg_fit') or template_data.get('fit')
            if 'position' not in bg_config:
                bg_config['position'] = template_data.get('bgPosition') or template_data.get('bg_position') or template_data.get('position')

        cls._draw_background(c, background_media, page_width, page_height, background_config=bg_config)

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

        # 4. Draw Mandatory System Verification QR Code
        if verification_url:
            qr_element = None
            elements = []
            if isinstance(template_data, dict):
                elements = template_data.get('elements', [])
            elif isinstance(template_data, list):
                elements = template_data

            for el in elements:
                if isinstance(el, dict) and (
                    el.get('type') == 'verification_qr' or
                    el.get('binding') == 'certificate.verification_url' or
                    el.get('id') == 'system-verification-qr' or
                    el.get('system') is True
                ):
                    qr_element = el
                    break

            qr_cfg = qr_element or template_data.get('qr_code', {
                'x': 0.85,
                'y': 0.82,
                'width': 0.12,
                'height': 0.12
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
    def _draw_background(cls, c, background_media, page_width, page_height, background_config=None):
        file_path = cls._resolve_media_path(background_media)
        if file_path and os.path.exists(file_path):
            try:
                bg_cfg = background_config or {}
                fit = bg_cfg.get('fit') or bg_cfg.get('bgFit') or bg_cfg.get('bg_fit') or 'cover'
                position = bg_cfg.get('position') or bg_cfg.get('bgPosition') or bg_cfg.get('bg_position') or 'center'

                with Image.open(file_path) as img:
                    img_w, img_h = img.size

                x, y, draw_w, draw_h = calculate_background_rect(
                    image_width=img_w,
                    image_height=img_h,
                    page_width=page_width,
                    page_height=page_height,
                    fit=fit,
                    position=position
                )

                c.saveState()
                clip_path = c.beginPath()
                clip_path.rect(0, 0, page_width, page_height)
                c.clipPath(clip_path, stroke=0, fill=0)

                c.drawImage(
                    file_path,
                    x,
                    y,
                    width=draw_w,
                    height=draw_h,
                    preserveAspectRatio=False,
                    mask='auto'
                )
                c.restoreState()
            except Exception as err:
                logger.warning(f"Failed to draw background image '{file_path}': {err}")

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
                    'binding': 'student.custom.certificate_name',
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
            text_value = item.get('text', item.get('static_text', ''))
            prefix = item.get('prefix', '')
            suffix = item.get('suffix', '')

            if binding and binding != 'static' and binding != 'static_text':
                val = snapshot_data.get(binding, '')
                text_value = f"{prefix}{val}{suffix}".strip() if val != '' else ''
            elif text_value:
                # Interpolate placeholders e.g. {{student.full_name}}
                for k, v in snapshot_data.items():
                    if isinstance(text_value, str) and f"{{{{{k}}}}}" in text_value:
                        text_value = text_value.replace(f"{{{{{k}}}}}", str(v))
                text_value = f"{prefix}{text_value}{suffix}".strip()

            if not text_value and item.get('type') != 'image':
                continue

            # Position parsing (Normalized center coordinates 0..1 or absolute pt coordinates)
            raw_x = item.get('x', 0.5)
            raw_y = item.get('y', 0.5)
            raw_width = item.get('width', 0.8)
            raw_height = item.get('height', 0.08)

            center_x = float(raw_x) * page_width if isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1 else float(raw_x)
            center_y_top = float(raw_y) * page_height if isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1 else float(raw_y)
            container_width = float(raw_width) * page_width if isinstance(raw_width, (int, float)) and 0 <= raw_width <= 1 else float(raw_width)
            container_height = float(raw_height) * page_height if isinstance(raw_height, (int, float)) and 0 <= raw_height <= 1 else float(raw_height)

            # Convert top-down center Y to bottom-up center Y for ReportLab
            center_y = page_height - center_y_top

            # Derive exact container bounds
            box_left = center_x - (container_width / 2.0)
            box_bottom = center_y - (container_height / 2.0)

            # Image element rendering
            if item.get('type') == 'image':
                img_url = item.get('image_url')
                if img_url:
                    img_path = cls._resolve_media_path(img_url)
                    if img_path and os.path.exists(img_path):
                        try:
                            c.drawImage(img_path, box_left, box_bottom, width=container_width, height=container_height, preserveAspectRatio=True, mask='auto')
                        except Exception:
                            pass
                continue

            base_max = item.get('fontSize') or item.get('font_size') or item.get('maxFontSize') or item.get('max_font_size')
            configured_max = float(base_max) if base_max is not None else 16.0
            configured_min = item.get('minFontSize') or item.get('min_font_size')
            min_font_size = float(configured_min) if configured_min is not None else 1.0
            auto_fit = item.get('auto_fit', item.get('autoFit', True))
            is_multiline = bool(item.get('multiline', False))
            line_height = float(item.get('lineHeight') or item.get('line_height') or 1.0)

            padding_cfg = item.get('padding') or {}
            if isinstance(padding_cfg, dict):
                pad_l = float(padding_cfg.get('left', 4.0))
                pad_r = float(padding_cfg.get('right', 4.0))
                pad_t = float(padding_cfg.get('top', 3.0))
                pad_b = float(padding_cfg.get('bottom', 3.0))
            elif isinstance(padding_cfg, (int, float)):
                pad_l = pad_r = pad_t = pad_b = float(padding_cfg)
            else:
                pad_l = pad_r = 4.0
                pad_t = pad_b = 3.0

            avail_width = max(1.0, container_width - (pad_l + pad_r))
            avail_height = max(1.0, container_height - (pad_t + pad_b))

            font_weight = str(item.get('font_weight', item.get('fontWeight', 'normal'))).lower()
            font_id = item.get('font_id') or item.get('fontId')
            font_key = item.get('font_key') or item.get('fontKey')
            font_family = item.get('font_family') or item.get('fontFamily')

            raw_font = font_id or font_key or font_family or 'Inter'

            academy_id = snapshot_data.get('academy_id') if isinstance(snapshot_data, dict) else None
            academy_obj = None
            if academy_id:
                from academy.models import Academy
                try:
                    academy_obj = Academy.objects.filter(id=academy_id).first()
                except Exception:
                    pass

            font_name = resolve_reportlab_font(raw_font, font_weight, academy=academy_obj)

            color_hex = str(item.get('color', item.get('fontColor', '#0F172A')))
            align = str(item.get('text_align', item.get('textAlign', 'center'))).lower()

            def test_text_fit(test_size: float) -> bool:
                if not is_multiline:
                    w = c.stringWidth(text_value, font_name, test_size)
                    h = test_size * line_height
                    return w <= avail_width and h <= avail_height
                else:
                    words = text_value.split()
                    if not words:
                        return True
                    lines = 1
                    cur_w = 0.0
                    space_w = c.stringWidth(" ", font_name, test_size)
                    for word in words:
                        word_w = c.stringWidth(word, font_name, test_size)
                        if word_w > avail_width:
                            return False
                        if cur_w == 0.0:
                            cur_w = word_w
                        elif cur_w + space_w + word_w <= avail_width:
                            cur_w += space_w + word_w
                        else:
                            lines += 1
                            cur_w = word_w
                    tot_h = lines * test_size * line_height
                    return tot_h <= avail_height

            # --- FONT FIT CALCULATOR (Starts from configured_max, only shrinks if overflow) ---
            fitted_font_size = configured_max
            if auto_fit and avail_width > 0 and avail_height > 0:
                cur_size = configured_max
                while cur_size >= min_font_size:
                    if test_text_fit(cur_size):
                        fitted_font_size = cur_size
                        break
                    cur_size -= 0.5
                else:
                    fitted_font_size = min_font_size

            c.saveState()

            clip_path = c.beginPath()
            clip_path.rect(box_left, box_bottom, container_width, container_height)
            c.clipPath(clip_path, stroke=0, fill=0)

            try:
                c.setFont(font_name, fitted_font_size)
            except Exception:
                c.setFont('Helvetica-Bold' if 'bold' in font_weight else 'Helvetica', fitted_font_size)

            try:
                c.setFillColor(HexColor(color_hex))
            except Exception:
                c.setFillColorRGB(0.06, 0.09, 0.16)

            # Center text vertically in container box matching CSS flex items-center
            draw_y = box_bottom + (container_height / 2.0) - (fitted_font_size * 0.35)

            if align == 'center':
                c.drawCentredString(center_x, draw_y, text_value)
            elif align == 'right':
                right_x = box_left + container_width - pad_r
                c.drawRightString(right_x, draw_y, text_value)
            else:
                left_x = box_left + pad_l
                c.drawString(left_x, draw_y, text_value)

            c.restoreState()

    @classmethod
    def _draw_qr_code(cls, c, url, cfg, page_width, page_height):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=6,
                border=3,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            img_bytes = io.BytesIO()
            try:
                img.save(img_bytes, format='PNG')
            except (TypeError, AttributeError):
                try:
                    img.save(img_bytes)
                except Exception:
                    save_obj = getattr(img, '_img', img)
                    try:
                        save_obj.save(img_bytes, format='PNG')
                    except TypeError:
                        save_obj.save(img_bytes)
            img_bytes.seek(0)
            image_reader = ImageReader(img_bytes)

            raw_x = cfg.get('x', 0.85)
            raw_y = cfg.get('y', 0.82)
            raw_w = cfg.get('width', 0.12)
            raw_h = cfg.get('height', 0.12)

            x = float(raw_x) * page_width if isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1 else float(raw_x)
            y = (1.0 - float(raw_y)) * page_height if isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1 else float(raw_y)
            w_pts = float(raw_w) * page_width if isinstance(raw_w, (int, float)) and 0 <= raw_w <= 1 else float(raw_w)
            h_pts = float(raw_h) * page_height if isinstance(raw_h, (int, float)) and 0 <= raw_h <= 1 else float(raw_h)

            # Preserve strict 1:1 aspect ratio
            side = max(10.0, min(w_pts, h_pts))
            draw_x = x - (side / 2.0) if isinstance(raw_x, (int, float)) and 0 <= raw_x <= 1 else x
            draw_y = y - (side / 2.0) if isinstance(raw_y, (int, float)) and 0 <= raw_y <= 1 else y

            c.drawImage(image_reader, draw_x, draw_y, width=side, height=side, mask='auto')
        except Exception:
            pass

