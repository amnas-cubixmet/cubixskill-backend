from rest_framework import serializers
from certificates.models import (
    CertificateTemplate,
    Certificate,
    CertificateIssueLog,
    CertificateSettings,
)

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
