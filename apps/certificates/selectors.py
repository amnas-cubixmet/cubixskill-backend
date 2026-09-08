from certificates.models import (
    Certificate,
    CertificateIssueLog,
    CertificateSettings,
    CertificateTemplate,
)
from django.db.models import QuerySet

#--------------------------------------------------------------
# CertificateSelector
#--------------------------------------------------------------

class CertificateSelector:

    @classmethod
    def get_public_verification_data(cls, verification_code: str) -> dict | None:
        """
        Retrieves public verification details for a given verification code.
        Never exposes internal IDs or sensitive student fields.
        """
        if verification_code == 'PREVIEW-DEMO':
            return {
                'valid': True,
                'is_preview': True,
                'certificate_number': 'CS-2026-PREVIEW',
                'verification_code': 'PREVIEW-DEMO',
                'student_name': 'Muhammed Ashraf Al Farooqi (Preview)',
                'course_name': 'Sample Course Completion Certificate Preview',
                'academy_name': 'CubixSkill Academy Preview',
                'issued_at': None,
                'completed_at': None,
                'status': 'PREVIEW',
                'revoked_at': None,
                'revocation_reason': None,
            }

        cert = Certificate.objects.select_related('course', 'course__academy').filter(
            verification_code=verification_code
        ).first()

        if not cert:
            return None

        is_valid = cert.status == 'ISSUED'

        return {
            'valid': is_valid,
            'is_preview': False,
            'certificate_number': cert.certificate_number,
            'verification_code': cert.verification_code,
            'student_name': cert.student_name_snapshot,
            'course_name': cert.course_name_snapshot,
            'academy_name': cert.academy_name_snapshot,
            'issued_at': cert.issued_at,
            'completed_at': cert.completed_at,
            'status': cert.status,
            'revoked_at': cert.revoked_at if cert.status == 'REVOKED' else None,
            'revocation_reason': cert.revocation_reason if cert.status == 'REVOKED' else None,
        }

    @classmethod
    def get_student_certificates(cls, student) -> QuerySet[Certificate]:
        """
        Queries all certificates belonging to a specific student.
        Filters out certificates for courses where COMPLETION_CERTIFICATE feature is disabled.
        """
        qs = Certificate.objects.filter(student=student).select_related(
            'course',
            'course__academy',
            'template',
            'pdf_media'
        ).order_by('-issued_at')

        from features.services import CourseFeatureService
        enabled_ids = [
            cert.id for cert in qs
            if not cert.course or CourseFeatureService.has_feature(cert.course, 'COMPLETION_CERTIFICATE')
        ]
        return Certificate.objects.filter(id__in=enabled_ids).select_related(
            'course',
            'course__academy',
            'template',
            'pdf_media'
        ).order_by('-issued_at')

    @classmethod
    def get_student_certificate_by_id(cls, student, certificate_id) -> Certificate | None:
        """
        Queries a single certificate for a student.
        """
        return Certificate.objects.filter(
            student=student,
            id=certificate_id
        ).select_related(
            'course',
            'course__academy',
            'template',
            'pdf_media'
        ).first()

    @classmethod
    def get_academy_certificates(cls, academy, search: str = None, status_filter: str = None, course_id: str = None, ordering: str = None) -> QuerySet[Certificate]:
        """
        Queries all certificates issued for a given academy with filtering and sorting.
        """
        from django.db.models import Q
        qs = Certificate.objects.filter(course__academy=academy).select_related(
            'student',
            'course',
            'template',
            'issued_by'
        )

        if status_filter and status_filter.upper() != 'ALL':
            qs = qs.filter(status=status_filter.upper())
        if course_id and course_id.lower() != 'all':
            qs = qs.filter(course_id=course_id)
        if search:
            qs = qs.filter(
                Q(certificate_number__icontains=search) |
                Q(student_name_snapshot__icontains=search) |
                Q(student__email__icontains=search) |
                Q(course_name_snapshot__icontains=search)
            )

        SORT_MAP = {
            'recent': '-issued_at',
            'newest': '-issued_at',
            '-issued_at': '-issued_at',
            'oldest': 'issued_at',
            'issued_at': 'issued_at',
            'student_asc': 'student_name_snapshot',
            'student_desc': '-student_name_snapshot',
            'course_asc': 'course_name_snapshot',
            'course_desc': '-course_name_snapshot',
        }
        order_field = SORT_MAP.get(ordering, '-issued_at') if ordering else '-issued_at'
        return qs.order_by(order_field)

    @classmethod
    def get_dashboard_metrics(cls, academy) -> dict:
        """
        Calculates summary metrics for an Academy's certificate domain.
        """
        from django.utils import timezone
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total = Certificate.objects.filter(course__academy=academy).count()
        issued_this_month = Certificate.objects.filter(course__academy=academy, issued_at__gte=month_start).count()
        active = Certificate.objects.filter(course__academy=academy, status='ISSUED').count()
        revoked = Certificate.objects.filter(course__academy=academy, status='REVOKED').count()

        return {
            'total_certificates': total,
            'issued_this_month': issued_this_month,
            'active_certificates': active,
            'revoked_certificates': revoked,
        }

    @classmethod
    def get_academy_templates(cls, academy) -> QuerySet[CertificateTemplate]:
        """
        Queries certificate templates belonging to an academy or global defaults.
        """
        return CertificateTemplate.objects.filter(
            academy=academy
        ).select_related('background_media').order_by('-created_at')

    @classmethod
    def get_certificate_logs(cls, certificate) -> QuerySet[CertificateIssueLog]:
        """
        Queries audit issue logs for a certificate.
        """
        return CertificateIssueLog.objects.filter(
            certificate=certificate
        ).select_related('performed_by').order_by('-occurred_at')

    @classmethod
    def get_or_create_academy_settings(cls, academy) -> CertificateSettings:
        """
        Gets or initializes CertificateSettings for an academy.
        """
        settings_obj, _ = CertificateSettings.objects.get_or_create(academy=academy)
        return settings_obj

DEFAULT_CERTIFICATE_FONTS = [
    {
        'key': 'inter',
        'name': 'Inter',
        'family': 'Inter',
        'font_weight_variants': ['400', '500', '600', '700', '800'],
        'file_url': 'https://fonts.gstatic.com/s/inter/v13/UcCO3Fwb07KITCgUn8g74g.woff2',
    },
    {
        'key': 'roboto',
        'name': 'Roboto',
        'family': 'Roboto',
        'font_weight_variants': ['300', '400', '500', '700'],
        'file_url': 'https://fonts.gstatic.com/s/roboto/v30/KFOmCnqEu92Fr1Mu4mxK.woff2',
    },
    {
        'key': 'open_sans',
        'name': 'Open Sans',
        'family': 'Open Sans',
        'font_weight_variants': ['400', '600', '700'],
        'file_url': 'https://fonts.gstatic.com/s/opensans/v35/memSYaGs126MiZpBA-UvWbX2vVnXBbObj2OVZyOOSr4dVJWUgsjZ0B4gaVQUwaEQbjB_sA.woff2',
    },
    {
        'key': 'lato',
        'name': 'Lato',
        'family': 'Lato',
        'font_weight_variants': ['300', '400', '700'],
        'file_url': 'https://fonts.gstatic.com/s/lato/v24/S6uyw4BMUTPHjx4wXiWtFCc.woff2',
    },
    {
        'key': 'montserrat',
        'name': 'Montserrat',
        'family': 'Montserrat',
        'font_weight_variants': ['400', '500', '600', '700', '800'],
        'file_url': 'https://fonts.gstatic.com/s/montserrat/v25/JTUHjIg1_i6t8kCHKm453WzAwr40suA.woff2',
    },
    {
        'key': 'merriweather',
        'name': 'Merriweather',
        'family': 'Merriweather',
        'font_weight_variants': ['300', '400', '700'],
        'file_url': 'https://fonts.gstatic.com/s/merriweather/v30/u-440qyqiXiFoYHpQa86YlIz2os.woff2',
    },
    {
        'key': 'playfair_display',
        'name': 'Playfair Display',
        'family': 'Playfair Display',
        'font_weight_variants': ['400', '600', '700', '800'],
        'file_url': 'https://fonts.gstatic.com/s/playfairdisplay/v30/nuFvD-vYSZviVYUb_RJ3ijvryePtLCAAGWQ.woff2',
    },
    {
        'key': 'cinzel',
        'name': 'Cinzel',
        'family': 'Cinzel',
        'font_weight_variants': ['400', '600', '700', '800'],
        'file_url': 'https://fonts.gstatic.com/s/cinzel/v19/8vLdf2_mCio6ioHY0955H6Q.woff2',
    },
]

class CertificateFontSelector:
    @classmethod
    def ensure_default_fonts(cls):
        from certificates.models import CertificateFont, FontSourceChoices
        for item in DEFAULT_CERTIFICATE_FONTS:
            CertificateFont.objects.get_or_create(
                key=item['key'],
                source=FontSourceChoices.SYSTEM,
                defaults={
                    'name': item['name'],
                    'family': item['family'],
                    'font_weight_variants': item['font_weight_variants'],
                    'file_url': item['file_url'],
                    'is_active': True,
                    'is_certificate_safe': True,
                }
            )

    @classmethod
    def get_available_fonts(cls, academy=None) -> QuerySet:
        from certificates.models import CertificateFont, FontSourceChoices
        cls.ensure_default_fonts()
        if academy:
            from django.db.models import Q
            return CertificateFont.objects.filter(
                Q(source=FontSourceChoices.SYSTEM) | Q(academy=academy, source=FontSourceChoices.ACADEMY),
                is_active=True
            ).select_related('media_file', 'academy').order_by('source', 'name')
        return CertificateFont.objects.filter(
            source=FontSourceChoices.SYSTEM,
            is_active=True
        ).select_related('media_file').order_by('name')
