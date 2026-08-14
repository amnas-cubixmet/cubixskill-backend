import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from certificates.models import (
    Certificate,
    CertificateTemplate,
    CertificateIssueLog,
    CertPDFMode,
    CertificateStatus,
    IssueLogEventType,
)
from certificates.generator import CertificatePDFGenerator
from learning_progress.models import CourseProgress, ProgressStatus
from enrollments.models import Enrollment

class CertificateService:

    @classmethod
    def generate_certificate_number(cls, academy=None) -> str:
        """
        Generates a unique human-readable certificate number e.g. CS-2026-X82A91.
        """
        prefix = 'CS'
        if academy and hasattr(academy, 'certificate_settings'):
            prefix = academy.certificate_settings.number_prefix.rstrip('-')

        year = timezone.now().strftime('%Y')

        while True:
            unique_part = uuid.uuid4().hex[:8].upper()
            cert_num = f"{prefix}-{year}-{unique_part}"
            if not Certificate.objects.filter(certificate_number=cert_num).exists():
                return cert_num

    @classmethod
    def generate_verification_code(cls) -> str:
        """
        Generates a unique verification code e.g. 7KQ9-2MPL-X82D.
        """
        while True:
            raw = uuid.uuid4().hex.upper()
            code = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"
            if not Certificate.objects.filter(verification_code=code).exists():
                return code

    @classmethod
    def is_eligible_for_certificate(cls, student, course) -> tuple[bool, str]:
        """
        Validates if a student is eligible for a course certificate.
        """
        if not course.certificate_enabled:
            return False, "Certificates are disabled for this course."

        # Check course progress
        progress = CourseProgress.objects.filter(student=student, course=course).first()
        if not progress:
            return False, "No progress recorded for this student in this course."

        if progress.status != ProgressStatus.COMPLETED and progress.progress_percent < 100.0:
            return False, "Course has not been fully completed."

        return True, "Eligible"

    @classmethod
    @transaction.atomic
    def issue_if_eligible(
        cls,
        student,
        course,
        issued_by=None,
        template=None,
        pdf_storage_mode=None,
        certificate_photo=None
    ) -> Certificate:
        """
        Idempotent issuance of a course certificate.
        """
        # 1. Idempotency Check: Return existing active certificate if already issued
        existing_cert = Certificate.objects.filter(
            student=student,
            course=course,
            status=CertificateStatus.ISSUED
        ).first()

        if existing_cert:
            return existing_cert

        # 2. Check Eligibility
        is_eligible, reason = cls.is_eligible_for_certificate(student, course)
        if not is_eligible:
            raise ValidationError(f"Cannot issue certificate: {reason}")

        # 3. Resolve Enrollment
        enrollment = Enrollment.objects.filter(student=student, course=course).first()

        # 4. Resolve Template
        if not template:
            if course.academy:
                template = CertificateTemplate.objects.filter(
                    academy=course.academy,
                    is_default=True,
                    is_active=True
                ).first() or CertificateTemplate.objects.filter(
                    academy=course.academy,
                    is_active=True
                ).first()

            if not template:
                template = CertificateTemplate.objects.filter(
                    academy__isnull=True,
                    is_active=True
                ).first()

        # 5. Snapshots
        student_name = getattr(student, 'display_name', '')
        if not student_name and hasattr(student, 'student_profile'):
            student_name = student.student_profile.display_name
        if not student_name:
            if hasattr(student, 'full_name') and student.full_name:
                student_name = student.full_name
            elif hasattr(student, 'get_full_name'):
                student_name = student.get_full_name()
            else:
                student_name = student.email

        course_name = course.title
        academy_name = course.academy.name if course.academy else 'CubixSkill'

        template_snapshot = {}
        if template:
            template_snapshot = {
                'id': str(template.id),
                'name': template.name,
                'template_data': template.template_data,
                'orientation': template.orientation,
                'page_size': template.page_size,
                'custom_width': str(template.custom_width) if template.custom_width is not None else None,
                'custom_height': str(template.custom_height) if template.custom_height is not None else None,
                'custom_unit': template.custom_unit,
                'show_student_photo': template.show_student_photo,
                'student_photo_shape': template.student_photo_shape,
                'background_media_id': str(template.background_media_id) if template.background_media_id else None,
            }

        # 6. Resolve PDF Storage Mode
        if not pdf_storage_mode:
            if course.academy and hasattr(course.academy, 'certificate_settings'):
                pdf_storage_mode = course.academy.certificate_settings.default_pdf_storage_mode
            else:
                pdf_storage_mode = CertPDFMode.ON_DEMAND

        # 7. Generate Numbers & Identifiers
        cert_num = cls.generate_certificate_number(course.academy)
        ver_code = cls.generate_verification_code()

        # Resolve completed_at date
        progress = CourseProgress.objects.filter(student=student, course=course).first()
        completed_at = progress.completed_at if (progress and progress.completed_at) else timezone.now()

        # 8. Create Certificate Record
        certificate = Certificate.objects.create(
            student=student,
            course=course,
            enrollment=enrollment,
            template=template,
            certificate_number=cert_num,
            verification_code=ver_code,
            student_name_snapshot=student_name,
            course_name_snapshot=course_name,
            academy_name_snapshot=academy_name,
            issued_at=timezone.now(),
            completed_at=completed_at,
            status=CertificateStatus.ISSUED,
            certificate_photo=certificate_photo,
            template_snapshot=template_snapshot,
            pdf_storage_mode=pdf_storage_mode,
            issued_by=issued_by
        )

        # 9. Create Issue Log
        CertificateIssueLog.objects.create(
            certificate=certificate,
            event_type=IssueLogEventType.ISSUED,
            performed_by=issued_by,
            reason="Certificate issued upon course completion",
            metadata={
                'pdf_storage_mode': pdf_storage_mode,
                'template_id': str(template.id) if template else None
            }
        )

        # 10. Persistent PDF storage if requested
        if pdf_storage_mode == CertPDFMode.STORED:
            cls.store_persistent_pdf(certificate)

        return certificate

    @classmethod
    def generate_pdf_bytes_for_certificate(cls, certificate: Certificate) -> bytes:
        """
        Renders PDF bytes from a Certificate instance using snapshot data.
        """
        snapshot_data = {
            'student_name': certificate.student_name_snapshot,
            'course_name': certificate.course_name_snapshot,
            'academy_name': certificate.academy_name_snapshot,
            'certificate_number': certificate.certificate_number,
            'verification_code': certificate.verification_code,
            'issue_date': certificate.issued_at.strftime('%B %d, %Y'),
            'completed_date': certificate.completed_at.strftime('%B %d, %Y') if certificate.completed_at else '',
        }

        template_snap = certificate.template_snapshot or {}
        template_data = template_snap.get('template_data', {})
        if not template_data and certificate.template:
            template_data = certificate.template.template_data

        orientation = template_snap.get('orientation', 'LANDSCAPE')
        page_size = template_snap.get('page_size', 'A4')
        custom_width = template_snap.get('custom_width') or (certificate.template.custom_width if certificate.template else None)
        custom_height = template_snap.get('custom_height') or (certificate.template.custom_height if certificate.template else None)
        custom_unit = template_snap.get('custom_unit') or (certificate.template.custom_unit if certificate.template else None)

        show_student_photo = template_snap.get('show_student_photo', False)
        student_photo_shape = template_snap.get('student_photo_shape', 'CIRCLE')

        # Background media resolution
        background_media = None
        if certificate.template and certificate.template.background_media:
            background_media = certificate.template.background_media

        # Student photo resolution priority:
        # 1. certificate_photo
        # 2. student.student_profile.profile_photo
        student_photo_media = certificate.certificate_photo
        if not student_photo_media and hasattr(certificate.student, 'student_profile'):
            student_photo_media = certificate.student.student_profile.profile_photo

        verification_url = f"/api/v1/certificates/verify/{certificate.verification_code}/"

        return CertificatePDFGenerator.generate_pdf(
            snapshot_data=snapshot_data,
            template_data=template_data,
            orientation=orientation,
            page_size=page_size,
            custom_width=custom_width,
            custom_height=custom_height,
            custom_unit=custom_unit,
            background_media=background_media,
            show_student_photo=show_student_photo,
            student_photo_shape=student_photo_shape,
            student_photo_media=student_photo_media,
            verification_url=verification_url
        )

    @classmethod
    def store_persistent_pdf(cls, certificate: Certificate):
        """
        Generates and saves persistent MediaFile for STORED mode certificates.
        """
        pdf_bytes = cls.generate_pdf_bytes_for_certificate(certificate)
        from storage.models import MediaFile, MediaType, MediaStatus
        from storage.services import StorageUsageService

        academy = certificate.course.academy
        filename = f"certificate_{certificate.certificate_number}.pdf"
        relative_path = f"certificates/{filename}"

        # Write file locally/S3
        full_dir = settings.MEDIA_ROOT / "certificates"
        full_dir.mkdir(parents=True, exist_ok=True)
        full_path = full_dir / filename
        with open(full_path, "wb") as f:
            f.write(pdf_bytes)

        media_file = MediaFile.objects.create(
            academy=academy,
            uploaded_by=certificate.issued_by or certificate.student,
            original_filename=filename,
            stored_filename=filename,
            storage_key=f"certificates/{certificate.verification_code}.pdf",
            relative_path=relative_path,
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes),
            media_type=MediaType.DOCUMENT,
            status=MediaStatus.ACTIVE,
            uploaded_at=timezone.now()
        )

        if academy:
            StorageUsageService.record_file_added(media_file)

        certificate.pdf_media = media_file
        certificate.save(update_fields=['pdf_media'])

    @classmethod
    @transaction.atomic
    def revoke_certificate(cls, certificate: Certificate, revoked_by, reason: str = "") -> Certificate:
        """
        Revokes an issued certificate.
        """
        if certificate.status == CertificateStatus.REVOKED:
            return certificate

        certificate.status = CertificateStatus.REVOKED
        certificate.revoked_at = timezone.now()
        certificate.revoked_by = revoked_by
        certificate.revocation_reason = reason
        certificate.save(update_fields=['status', 'revoked_at', 'revoked_by', 'revocation_reason'])

        CertificateIssueLog.objects.create(
            certificate=certificate,
            event_type=IssueLogEventType.REVOKED,
            performed_by=revoked_by,
            reason=reason
        )

        return certificate

    @classmethod
    @transaction.atomic
    def reissue_certificate(
        cls,
        certificate: Certificate,
        reissued_by,
        reason: str = "",
        new_template=None
    ) -> Certificate:
        """
        Reissues a certificate without destroying historical record.
        """
        # Mark original certificate as REISSUED
        certificate.status = CertificateStatus.REISSUED
        certificate.save(update_fields=['status'])

        CertificateIssueLog.objects.create(
            certificate=certificate,
            event_type=IssueLogEventType.REISSUED,
            performed_by=reissued_by,
            reason=reason
        )

        # Issue new certificate referencing reissued_from
        new_cert = cls.issue_if_eligible(
            student=certificate.student,
            course=certificate.course,
            issued_by=reissued_by,
            template=new_template or certificate.template,
            pdf_storage_mode=certificate.pdf_storage_mode,
            certificate_photo=certificate.certificate_photo
        )

        new_cert.reissued_from = certificate
        new_cert.save(update_fields=['reissued_from'])
        return new_cert

    @classmethod
    def preview_template(cls, template: CertificateTemplate, sample_data: dict = None) -> bytes:
        """
        Generates sample PDF bytes for template preview without creating DB records.
        """
        sample_snapshot = {
            'student_name': 'John Doe',
            'course_name': 'Sample Masterclass Course',
            'academy_name': template.academy.name if template.academy else 'CubixSkill Academy',
            'certificate_number': 'CS-2026-PREVIEW01',
            'verification_code': 'PREVIEW-CODE-1234',
            'issue_date': timezone.now().strftime('%B %d, %Y'),
            'completed_date': timezone.now().strftime('%B %d, %Y'),
        }

        if sample_data:
            sample_snapshot.update(sample_data)

        verification_url = f"/api/v1/certificates/verify/{sample_snapshot['verification_code']}/"

        return CertificatePDFGenerator.generate_pdf(
            snapshot_data=sample_snapshot,
            template_data=template.template_data,
            orientation=template.orientation,
            page_size=template.page_size,
            custom_width=template.custom_width,
            custom_height=template.custom_height,
            custom_unit=template.custom_unit,
            background_media=template.background_media,
            show_student_photo=template.show_student_photo,
            student_photo_shape=template.student_photo_shape,
            student_photo_media=None,
            verification_url=verification_url
        )
