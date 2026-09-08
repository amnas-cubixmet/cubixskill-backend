from certificates.models import (
    Certificate,
    CertificateIssueLog,
    CertificateSettings,
    CertificateTemplate,
)
from django.contrib import admin


@admin.register(CertificateSettings)
class CertificateSettingsAdmin(admin.ModelAdmin):
    list_display = ('academy', 'default_pdf_storage_mode', 'number_prefix', 'enable_qr_verification', 'created_at')
    search_fields = ('academy__name', 'number_prefix')

@admin.register(CertificateTemplate)
class CertificateTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'academy', 'orientation', 'page_size', 'custom_width', 'custom_height', 'custom_unit', 'show_student_photo', 'is_default', 'is_active', 'created_at')
    list_filter = ('orientation', 'page_size', 'custom_unit', 'show_student_photo', 'is_default', 'is_active', 'academy')
    search_fields = ('name', 'description', 'academy__name')

class CertificateIssueLogInline(admin.TabularInline):
    model = CertificateIssueLog
    extra = 0
    readonly_fields = ('event_type', 'performed_by', 'reason', 'occurred_at', 'metadata')
    can_delete = False

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = (
        'certificate_number',
        'student_name_snapshot',
        'course_name_snapshot',
        'academy_name_snapshot',
        'status',
        'pdf_storage_mode',
        'issued_at'
    )
    list_filter = ('status', 'pdf_storage_mode', 'issued_at')
    search_fields = (
        'certificate_number',
        'verification_code',
        'student_name_snapshot',
        'course_name_snapshot',
        'academy_name_snapshot'
    )
    readonly_fields = (
        'certificate_number',
        'verification_code',
        'student_name_snapshot',
        'course_name_snapshot',
        'academy_name_snapshot',
        'template_snapshot',
        'issued_at'
    )
    inlines = [CertificateIssueLogInline]

@admin.register(CertificateIssueLog)
class CertificateIssueLogAdmin(admin.ModelAdmin):
    list_display = ('certificate', 'event_type', 'performed_by', 'occurred_at')
    list_filter = ('event_type', 'occurred_at')
    search_fields = ('certificate__certificate_number', 'reason')
