from django.db import models
from django.utils import timezone
from core.models import BaseModel, ActiveMixin

#--------------------------------------------------------------
# OrientationChoices
#--------------------------------------------------------------

class OrientationChoices(models.TextChoices):
    LANDSCAPE = 'LANDSCAPE', 'Landscape'
    PORTRAIT = 'PORTRAIT', 'Portrait'

#--------------------------------------------------------------
# PageSizeChoices
#--------------------------------------------------------------

class PageSizeChoices(models.TextChoices):
    A4 = 'A4', 'A4'
    LETTER = 'LETTER', 'Letter'
    CUSTOM = 'CUSTOM', 'Custom'

#--------------------------------------------------------------
# UnitChoices
#--------------------------------------------------------------

class UnitChoices(models.TextChoices):
    MM = 'MM', 'Millimeters (mm)'
    CM = 'CM', 'Centimeters (cm)'
    INCH = 'INCH', 'Inches (in)'

#--------------------------------------------------------------
# PhotoShapeChoices
#--------------------------------------------------------------

class PhotoShapeChoices(models.TextChoices):
    CIRCLE = 'CIRCLE', 'Circle'
    RECTANGLE = 'RECTANGLE', 'Rectangle'
    SQUARE = 'SQUARE', 'Square'

#--------------------------------------------------------------
# CertPDFMode
#--------------------------------------------------------------

class CertPDFMode(models.TextChoices):
    ON_DEMAND = 'ON_DEMAND', 'On Demand Generation'
    STORED = 'STORED', 'Permanently Stored PDF'

#--------------------------------------------------------------
# CertificateStatus
#--------------------------------------------------------------

class CertificateStatus(models.TextChoices):
    ISSUED = 'ISSUED', 'Issued'
    REVOKED = 'REVOKED', 'Revoked'
    REISSUED = 'REISSUED', 'Reissued'
    VOID = 'VOID', 'Void'

class FontSourceChoices(models.TextChoices):
    SYSTEM = 'SYSTEM', 'System Default Font'
    ACADEMY = 'ACADEMY', 'Academy Uploaded Font'

#--------------------------------------------------------------
# CertificateFont
#--------------------------------------------------------------

class CertificateFont(BaseModel, ActiveMixin):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='uploaded_certificate_fonts'
    )
    key = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=255)
    family = models.CharField(max_length=255)
    source = models.CharField(
        max_length=20,
        choices=FontSourceChoices.choices,
        default=FontSourceChoices.SYSTEM
    )
    user_rights_confirmed = models.BooleanField(default=False)
    media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    file_url = models.CharField(max_length=500, blank=True, default='')
    font_weight_variants = models.JSONField(default=list)
    is_certificate_safe = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'certificate_fonts'
        ordering = ['source', 'name']

    def __str__(self):
        return f"{self.name} ({self.source})"

#--------------------------------------------------------------
# IssueLogEventType
#--------------------------------------------------------------

class IssueLogEventType(models.TextChoices):
    ISSUED = 'ISSUED', 'Issued'
    DOWNLOADED = 'DOWNLOADED', 'Downloaded'
    REISSUED = 'REISSUED', 'Reissued'
    REVOKED = 'REVOKED', 'Revoked'
    RESTORED = 'RESTORED', 'Restored'

#--------------------------------------------------------------
# CertificateSettings
#--------------------------------------------------------------

class CertificateSettings(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='certificate_settings'
    )
    default_pdf_storage_mode = models.CharField(
        max_length=20,
        choices=CertPDFMode.choices,
        default=CertPDFMode.ON_DEMAND
    )
    number_prefix = models.CharField(max_length=20, default='CS-')
    enable_qr_verification = models.BooleanField(default=True)

    class Meta:
        db_table = 'certificate_settings'

    def __str__(self):
        return f"Certificate Settings ({self.academy.name})"

#--------------------------------------------------------------
# CertificateTemplate
#--------------------------------------------------------------

class CertificateTemplate(BaseModel, ActiveMixin):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='certificate_templates'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    template_data = models.JSONField(default=dict)
    orientation = models.CharField(
        max_length=20,
        choices=OrientationChoices.choices,
        default=OrientationChoices.LANDSCAPE
    )
    page_size = models.CharField(
        max_length=20,
        choices=PageSizeChoices.choices,
        default=PageSizeChoices.A4
    )

    custom_width = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    custom_height = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    custom_unit = models.CharField(
        max_length=10,
        choices=UnitChoices.choices,
        null=True,
        blank=True
    )

    background_media = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    show_student_photo = models.BooleanField(default=False)
    student_photo_shape = models.CharField(
        max_length=20,
        choices=PhotoShapeChoices.choices,
        default=PhotoShapeChoices.CIRCLE
    )
    student_photo_position = models.JSONField(default=dict, blank=True)

    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = 'certificate_templates'
        ordering = ['-created_at']

    def __str__(self):
        academy_str = self.academy.name if self.academy else 'Global'
        return f"{self.name} - {academy_str}"

    def save(self, *args, **kwargs):
        if self.page_size != PageSizeChoices.CUSTOM:
            self.custom_width = None
            self.custom_height = None
            self.custom_unit = None

        if self.is_default and self.academy:
            CertificateTemplate.objects.filter(
                academy=self.academy,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

#--------------------------------------------------------------
# CertificateTemplateVersion
#--------------------------------------------------------------

class CertificateTemplateVersion(BaseModel):
    template = models.ForeignKey(
        CertificateTemplate,
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.IntegerField(default=1)
    background_media = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    canvas_width = models.DecimalField(max_digits=8, decimal_places=2, default=1600.0)
    canvas_height = models.DecimalField(max_digits=8, decimal_places=2, default=1131.0)
    layout_json = models.JSONField(default=list)
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        db_table = 'certificate_template_versions'
        unique_together = ('template', 'version_number')
        ordering = ['-version_number']

    def __str__(self):
        return f"{self.template.name} (v{self.version_number})"

#--------------------------------------------------------------
# CourseCertificateConfig
#--------------------------------------------------------------

class CourseCertificateConfig(BaseModel):
    course = models.OneToOneField(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='certificate_config'
    )
    template = models.ForeignKey(
        CertificateTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='course_configs'
    )
    auto_issue = models.BooleanField(default=True)
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'course_certificate_configs'

    def __str__(self):
        return f"Certificate Config for {self.course.title}"

#--------------------------------------------------------------
# Certificate
#--------------------------------------------------------------

class Certificate(BaseModel):
    student = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='certificates'
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='issued_certificates'
    )
    enrollment = models.ForeignKey(
        'enrollments.Enrollment',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='certificates'
    )
    template = models.ForeignKey(
        CertificateTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_certificates'
    )
    template_version = models.ForeignKey(
        CertificateTemplateVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_certificates'
    )

    certificate_number = models.CharField(max_length=100, unique=True, db_index=True)
    verification_code = models.CharField(max_length=100, unique=True, db_index=True)

    student_name_snapshot = models.CharField(max_length=255)
    course_name_snapshot = models.CharField(max_length=255)
    academy_name_snapshot = models.CharField(max_length=255)
    custom_data_snapshot = models.JSONField(default=dict, blank=True)

    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(default=timezone.now)

    status = models.CharField(
        max_length=20,
        choices=CertificateStatus.choices,
        default=CertificateStatus.ISSUED,
        db_index=True
    )

    certificate_photo = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    template_snapshot = models.JSONField(default=dict)

    pdf_storage_mode = models.CharField(
        max_length=20,
        choices=CertPDFMode.choices,
        default=CertPDFMode.ON_DEMAND
    )
    pdf_media = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    issued_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    revocation_reason = models.TextField(blank=True, default='')

    reissued_from = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reissues'
    )

    class Meta:
        db_table = 'certificates'
        ordering = ['-issued_at']

    def __str__(self):
        return f"Certificate {self.certificate_number} - {self.student_name_snapshot}"

#--------------------------------------------------------------
# CertificateIssueLog
#--------------------------------------------------------------

class CertificateIssueLog(BaseModel):
    certificate = models.ForeignKey(
        Certificate,
        on_delete=models.CASCADE,
        related_name='issue_logs'
    )
    event_type = models.CharField(
        max_length=50,
        choices=IssueLogEventType.choices,
        default=IssueLogEventType.ISSUED
    )
    performed_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    reason = models.TextField(blank=True, default='')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'certificate_issue_logs'
        ordering = ['-occurred_at']

    def __str__(self):
        return f"{self.event_type} on {self.certificate.certificate_number} at {self.occurred_at}"
