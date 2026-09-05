from rest_framework import serializers
from certificates.models import (
    CertificateTemplate,
    Certificate,
    CertificateIssueLog,
    CertificateSettings,
    CertificateFont,
)

class CertificateFontSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    runtime_family = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = CertificateFont
        fields = [
            'id',
            'key',
            'name',
            'family',
            'display_name',
            'runtime_family',
            'source',
            'user_rights_confirmed',
            'file_url',
            'font_weight_variants',
            'is_active',
            'is_certificate_safe',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_display_name(self, obj) -> str:
        return obj.name or obj.family

    def get_runtime_family(self, obj) -> str:
        if obj.source == 'ACADEMY':
            return f"cubix-font-{obj.id}"
        return obj.family

    def get_file_url(self, obj) -> str:
        if obj.media_file:
            raw_path = getattr(obj.media_file, 'file_url', '') or getattr(obj.media_file, 'relative_path', '')
            if raw_path and not raw_path.startswith('/media/') and not raw_path.startswith('http'):
                return f"/media/{raw_path.lstrip('/')}"
            return raw_path or obj.file_url
        return obj.file_url or ''

class CertificateFontUploadSerializer(serializers.Serializer):
    font_file = serializers.FileField(required=True)
    display_name = serializers.CharField(max_length=255, required=True)
    user_rights_confirmed = serializers.BooleanField(required=True)

    def validate_user_rights_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("You must confirm you have the necessary rights to use and embed this font.")
        return value

    def validate_font_file(self, value):
        ext = value.name.split('.')[-1].lower()
        if ext not in ['ttf', 'otf', 'woff', 'woff2']:
            raise serializers.ValidationError("Only .ttf, .otf, .woff, and .woff2 font formats are supported.")
        if value.size > 15 * 1024 * 1024:
            raise serializers.ValidationError("Font file size must not exceed 15MB.")

        # Read first 16 bytes for binary magic header validation
        try:
            value.seek(0)
            header = value.read(16)
            value.seek(0)

            # Magic headers:
            # TTF / TrueType: \x00\x01\x00\x00 or 'true' (\x74\x72\x75\x65)
            # OTF / OpenType: 'OTTO' (\x4F\x54\x54\x4F)
            # WOFF: 'wOFF' (\x77\x4F\x46\x46)
            # WOFF2: 'wOF2' (\x77\x4F\x46\x32)
            is_valid_binary = (
                header.startswith(b'\x00\x01\x00\x00') or
                header.startswith(b'OTTO') or
                header.startswith(b'wOFF') or
                header.startswith(b'wOF2') or
                header.startswith(b'true')
            )
            if not is_valid_binary:
                raise serializers.ValidationError("The uploaded file is not a valid font binary.")
        except Exception as e:
            if isinstance(e, serializers.ValidationError):
                raise e
            raise serializers.ValidationError("Failed to validate binary signature of font file.")

        return value

#--------------------------------------------------------------
# CertificateTemplateSerializer
#--------------------------------------------------------------

class CertificateTemplateSerializer(serializers.ModelSerializer):
    background_media_url = serializers.SerializerMethodField()

    class Meta:
        model = CertificateTemplate
        fields = [
            'id',
            'academy',
            'name',
            'description',
            'template_data',
            'orientation',
            'page_size',
            'custom_width',
            'custom_height',
            'custom_unit',
            'background_media',
            'background_media_url',
            'show_student_photo',
            'student_photo_shape',
            'student_photo_position',
            'is_default',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_background_media_url(self, obj) -> str | None:
        if obj.background_media:
            return getattr(obj.background_media, 'relative_path', None)
        return None

    def validate(self, attrs):
        page_size = attrs.get('page_size', self.instance.page_size if self.instance else 'A4')

        if page_size == 'CUSTOM':
            custom_width = attrs.get('custom_width', self.instance.custom_width if self.instance else None)
            custom_height = attrs.get('custom_height', self.instance.custom_height if self.instance else None)
            custom_unit = attrs.get('custom_unit', self.instance.custom_unit if self.instance else None)

            errors = {}
            if custom_width is None:
                errors['custom_width'] = "custom_width is required when page_size is CUSTOM."
            if custom_height is None:
                errors['custom_height'] = "custom_height is required when page_size is CUSTOM."
            if not custom_unit:
                errors['custom_unit'] = "custom_unit is required when page_size is CUSTOM."

            if errors:
                raise serializers.ValidationError(errors)

            if float(custom_width) <= 0:
                raise serializers.ValidationError({"custom_width": "custom_width must be greater than 0."})
            if float(custom_height) <= 0:
                raise serializers.ValidationError({"custom_height": "custom_height must be greater than 0."})

            unit_mm_factor = {'MM': 1.0, 'CM': 10.0, 'INCH': 25.4}
            factor = unit_mm_factor.get(str(custom_unit).upper(), 1.0)
            width_mm = float(custom_width) * factor
            height_mm = float(custom_height) * factor

            if width_mm < 50 or width_mm > 2000:
                raise serializers.ValidationError({"custom_width": "custom_width must be between 50 mm and 2000 mm (or equivalent)."})
            if height_mm < 50 or height_mm > 2000:
                raise serializers.ValidationError({"custom_height": "custom_height must be between 50 mm and 2000 mm (or equivalent)."})
        else:
            attrs['custom_width'] = None
            attrs['custom_height'] = None
            attrs['custom_unit'] = None

        # Validate template_data font references for academy tenant isolation
        template_data = attrs.get('template_data', self.instance.template_data if self.instance else None)
        if template_data and isinstance(template_data, dict):
            elements = template_data.get('elements', [])
            if isinstance(elements, list):
                request = self.context.get('request')
                academy = getattr(request.user, 'academy', None) if request and hasattr(request, 'user') else None
                if not academy and self.instance:
                    academy = self.instance.academy

                from certificates.selectors import CertificateFontSelector
                available_fonts = CertificateFontSelector.get_available_fonts(academy)
                valid_keys = set(available_fonts.values_list('key', flat=True))
                valid_ids = set(str(fid) for fid in available_fonts.values_list('id', flat=True))
                valid_families = set(f.lower() for f in available_fonts.values_list('family', flat=True))

                for el in elements:
                    if isinstance(el, dict):
                        font_id = str(el.get('fontId') or el.get('font_id') or '')
                        font_key = el.get('fontKey') or el.get('font_key')
                        font_fam = el.get('font_family') or el.get('fontFamily') or ''
                        
                        # Validate font reference if provided
                        if font_id and font_id in valid_ids:
                            continue
                        if font_key and font_key in valid_keys:
                            continue
                        if font_fam:
                            if font_fam.lower() in valid_families or font_fam.startswith('cubix-font-'):
                                continue
                        if font_key and font_key not in valid_keys and (font_fam and font_fam.lower() not in valid_families):
                            raise serializers.ValidationError({
                                "template_data": f"Font '{font_key or font_fam or font_id}' is not available for this academy."
                            })

        return attrs

#--------------------------------------------------------------
# CertificateSettingsSerializer
#--------------------------------------------------------------

class CertificateSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificateSettings
        fields = [
            'id',
            'academy',
            'default_pdf_storage_mode',
            'number_prefix',
            'enable_qr_verification',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'academy', 'created_at', 'updated_at']

#--------------------------------------------------------------
# CertificateIssueLogSerializer
#--------------------------------------------------------------

class CertificateIssueLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CertificateIssueLog
        fields = [
            'id',
            'certificate',
            'event_type',
            'performed_by',
            'performed_by_name',
            'reason',
            'occurred_at',
            'metadata',
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj) -> str | None:
        if obj.performed_by:
            if hasattr(obj.performed_by, 'full_name') and obj.performed_by.full_name:
                return obj.performed_by.full_name
            if hasattr(obj.performed_by, 'get_full_name'):
                return obj.performed_by.get_full_name()
            return obj.performed_by.email
        return None

#--------------------------------------------------------------
# CertificateSerializer
#--------------------------------------------------------------

class CertificateSerializer(serializers.ModelSerializer):
    pdf_download_url = serializers.SerializerMethodField()
    issue_logs = CertificateIssueLogSerializer(many=True, read_only=True)

    class Meta:
        model = Certificate
        fields = [
            'id',
            'student',
            'course',
            'enrollment',
            'template',
            'certificate_number',
            'verification_code',
            'student_name_snapshot',
            'course_name_snapshot',
            'academy_name_snapshot',
            'issued_at',
            'completed_at',
            'status',
            'certificate_photo',
            'template_snapshot',
            'pdf_storage_mode',
            'pdf_media',
            'pdf_download_url',
            'issued_by',
            'revoked_at',
            'revoked_by',
            'revocation_reason',
            'reissued_from',
            'issue_logs',
            'created_at',
        ]
        read_only_fields = fields

    def get_pdf_download_url(self, obj) -> str:
        return f"/api/v1/student/certificates/{obj.id}/download/"

#--------------------------------------------------------------
# StudentCertificateListSerializer
#--------------------------------------------------------------

class StudentCertificateListSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course_name_snapshot', read_only=True)
    academy_name = serializers.CharField(source='academy_name_snapshot', read_only=True)
    pdf_download_url = serializers.SerializerMethodField()

    class Meta:
        model = Certificate
        fields = [
            'id',
            'certificate_number',
            'verification_code',
            'student_name_snapshot',
            'course_title',
            'academy_name',
            'issued_at',
            'completed_at',
            'status',
            'pdf_storage_mode',
            'pdf_download_url',
        ]

    def get_pdf_download_url(self, obj) -> str:
        return f"/api/v1/student/certificates/{obj.id}/download/"

#--------------------------------------------------------------
# PublicVerificationSerializer
#--------------------------------------------------------------

class PublicVerificationSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    certificate_number = serializers.CharField()
    verification_code = serializers.CharField()
    student_name = serializers.CharField()
    course_name = serializers.CharField()
    academy_name = serializers.CharField()
    issued_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField()
    status = serializers.CharField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    revocation_reason = serializers.CharField(allow_blank=True, allow_null=True)

#--------------------------------------------------------------
# ManualIssueCertificateSerializer
#--------------------------------------------------------------

class ManualIssueCertificateSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    course_id = serializers.UUIDField()
    template_id = serializers.UUIDField(required=False, allow_null=True)
    pdf_storage_mode = serializers.CharField(required=False, allow_null=True)
    certificate_photo_id = serializers.UUIDField(required=False, allow_null=True)

#--------------------------------------------------------------
# RevokeCertificateSerializer
#--------------------------------------------------------------

class RevokeCertificateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')

#--------------------------------------------------------------
# ReissueCertificateSerializer
#--------------------------------------------------------------

class ReissueCertificateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    template_id = serializers.UUIDField(required=False, allow_null=True)

#--------------------------------------------------------------
# TemplatePreviewSerializer
#--------------------------------------------------------------

class TemplatePreviewSerializer(serializers.Serializer):
    sample_student_name = serializers.CharField(required=False, default='John Doe')
    sample_course_name = serializers.CharField(required=False, default='Sample Masterclass')
    sample_academy_name = serializers.CharField(required=False, default='CubixSkill Academy')
