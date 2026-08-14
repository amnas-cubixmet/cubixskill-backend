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
    def get_academy_certificates(cls, academy) -> QuerySet[Certificate]:
        """
        Queries all certificates issued for a given academy.
        """
        return Certificate.objects.filter(course__academy=academy).select_related(
            'student',
            'course',
            'template',
            'issued_by'
        ).order_by('-issued_at')

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
