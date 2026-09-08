import logging
import os

logger = logging.getLogger(__name__)

class FontValidationResult:
    def __init__(self, is_valid: bool, format_ext: str, outline_type: str, is_pdf_compatible: bool, error_message: str = ''):
        self.is_valid = is_valid
        self.format_ext = format_ext
        self.outline_type = outline_type
        self.is_pdf_compatible = is_pdf_compatible
        self.error_message = error_message

    def to_dict(self):
        return {
            "is_valid": self.is_valid,
            "format_ext": self.format_ext,
            "outline_type": self.outline_type,
            "is_pdf_compatible": self.is_pdf_compatible,
            "error_message": self.error_message
        }


class CertificateFontValidator:
    """
    Authoritative backend validator for certificate font binary files.
    Inspects container format, sfnt flavor, and outline technology using fontTools.
    Tests actual PDF engine embeddability using ReportLab TTFont registration.
    """

    @classmethod
    def inspect_and_validate_font(cls, file_or_path, font_id_str: str = 'test') -> FontValidationResult:
        # Determine if file_or_path is path or file object
        file_path = None
        is_temp_file = False

        if isinstance(file_or_path, str):
            file_path = file_or_path
        else:
            # File-like object (e.g., UploadedFile)
            import tempfile
            file_or_path.seek(0)
            raw_ext = (getattr(file_or_path, 'name', '').split('.')[-1] if '.' in getattr(file_or_path, 'name', '') else 'bin').lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{raw_ext}") as tmp:
                for chunk in file_or_path.chunks() if hasattr(file_or_path, 'chunks') else [file_or_path.read()]:
                    tmp.write(chunk)
                file_path = tmp.name
                is_temp_file = True
            file_or_path.seek(0)

        format_ext = 'TTF'
        outline_type = 'TRUETYPE'
        is_pdf_compatible = True
        error_message = ''

        try:
            from fontTools.ttLib import TTFont as FTFont
            try:
                ft_inspect = FTFont(file_path)
                sfnt_ver = getattr(ft_inspect, 'sfntVersion', '')

                if 'CFF ' in ft_inspect or 'CFF2' in ft_inspect or sfnt_ver == 'OTTO':
                    outline_type = 'CFF'
                    format_ext = 'OTF'
                elif 'glyf' in ft_inspect or sfnt_ver in ['\x00\x01\x00\x00', 'true']:
                    outline_type = 'TRUETYPE'
                    format_ext = 'TTF' if not file_path.lower().endswith('.otf') else 'OTF'
                elif sfnt_ver in ['wOFF', 'wOF2']:
                    format_ext = sfnt_ver.upper()
                    outline_type = 'CFF' if ('CFF ' in ft_inspect or 'CFF2' in ft_inspect) else 'TRUETYPE'

                ft_inspect.close()
            except Exception as inspect_err:
                logger.warning(f"fontTools failed to inspect font '{file_path}': {inspect_err}")
                raw_ext = (file_path.split('.')[-1] if '.' in file_path else 'TTF').upper()
                format_ext = raw_ext if raw_ext in ['TTF', 'OTF', 'WOFF', 'WOFF2'] else 'TTF'

            # 1. Reject browser-only WOFF/WOFF2
            if format_ext in ['WOFF', 'WOFF2']:
                return FontValidationResult(
                    is_valid=False,
                    format_ext=format_ext,
                    outline_type=outline_type,
                    is_pdf_compatible=False,
                    error_message=f"Font format '{format_ext}' is browser-only and cannot be embedded in certificate PDFs."
                )

            # 2. Test ReportLab TTFont PDF engine registration (attempt OTF/CFF conversion if needed)
            from certificates.generator import convert_otf_cff_to_ttf
            usable_test_path = file_path
            if outline_type == 'CFF' or format_ext == 'OTF' or file_path.lower().endswith('.otf'):
                usable_test_path = convert_otf_cff_to_ttf(file_path)

            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont as RLTTFont
            test_reg_name = f"CubixFont_Validate_{font_id_str.replace('-', '')}"

            try:
                if test_reg_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(RLTTFont(test_reg_name, usable_test_path))
                is_pdf_compatible = True
            except Exception as rl_err:
                is_pdf_compatible = False
                err_str = str(rl_err)
                if 'postscript outlines are not supported' in err_str.lower() and usable_test_path == file_path:
                    error_message = "This font uses PostScript/CFF outlines and could not be converted to TrueType for certificate PDF generation. Please upload a TrueType-outline TTF font."
                else:
                    error_message = f"Font registration failed for certificate PDF generator: {err_str}"

                return FontValidationResult(
                    is_valid=False,
                    format_ext=format_ext,
                    outline_type=outline_type,
                    is_pdf_compatible=False,
                    error_message=error_message
                )

            return FontValidationResult(
                is_valid=True,
                format_ext=format_ext,
                outline_type=outline_type,
                is_pdf_compatible=is_pdf_compatible
            )

        finally:
            if is_temp_file and file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
