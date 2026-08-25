from django.db.models import QuerySet
from certificates.models import (
    Certificate,
    CertificateTemplate,
    CertificateIssueLog,
    CertificateSettings,
)

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
        cert = Certificate.objects.select_related('course', 'course__academy').filter(
            verification_code=verification_code
        ).first()

        if not cert:
            return None

        is_valid = cert.status == 'ISSUED'

        return {
            'valid': is_valid,
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
        """
        return Certificate.objects.filter(student=student).select_related(
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
