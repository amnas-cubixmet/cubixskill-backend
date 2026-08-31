import uuid
from typing import Dict, Any
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
from students.models import StudentCustomFieldValue


class CertificateDataResolver:
    """
    Authoritative backend data resolver for certificate template fields.
    Resolves system, course, student, enrollment, score, and custom fields.
    """

    @classmethod
    def resolve_data(
        cls,
        student=None,
        course=None,
        enrollment=None,
        certificate=None,
        custom_overrides: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}

        # 1. Student Fields
        if student:
            user = getattr(student, 'user', None)
            first_name = getattr(student, 'first_name', '') or getattr(user, 'first_name', '')
            last_name = getattr(student, 'last_name', '') or getattr(user, 'last_name', '')
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                full_name = getattr(student, 'full_name', '') or getattr(student, 'display_name', '') or (user.get_full_name() if user and hasattr(user, 'get_full_name') else '') or str(user or '')
            
            data['student.full_name'] = full_name
            data['student.first_name'] = first_name
            data['student.last_name'] = last_name
            data['student.email'] = getattr(user, 'email', '') or getattr(student, 'email', '')
            data['student.phone'] = getattr(student, 'phone_number', '') or getattr(student, 'phone', '')
            data['student.code'] = str(getattr(student, 'student_code', '') or getattr(student, 'id', ''))

            # Resolve Custom Student Fields
            profile = getattr(student, 'student_profile', None)
            if profile:
                custom_vals = StudentCustomFieldValue.objects.filter(student=profile).select_related('field_definition')
                for cv in custom_vals:
                    key_name = f"student.custom.{cv.field_definition.key}"
                    data[key_name] = cv.value

        # 2. Course Fields
        if course:
            data['course.title'] = course.title
            data['course.code'] = getattr(course, 'code', '') or course.title[:6].upper()
            data['course.category'] = getattr(course.category, 'name', '') if getattr(course, 'category', None) else ''
            data['course.level'] = getattr(course, 'level', '')
            if course.academy:
                data['academy.name'] = course.academy.name
                inst = getattr(course, 'instructor', None)
                data['instructor.name'] = getattr(inst, 'display_name', '') if inst else course.academy.name

        # 3. Enrollment Fields
        if enrollment or (student and course):
            if not enrollment and student and course:
                enrollment = Enrollment.objects.filter(student=student, course=course).first()
            if enrollment:
                data['enrollment.enrolled_at'] = enrollment.enrolled_at.strftime('%d %b %Y') if getattr(enrollment, 'enrolled_at', None) else ''
                data['enrollment.status'] = enrollment.status

            progress = CourseProgress.objects.filter(student=student, course=course).first() if (student and course) else None
            if progress:
                data['enrollment.completed_at'] = progress.completed_at.strftime('%d %b %Y') if progress.completed_at else ''
                data['enrollment.progress_percent'] = f"{int(progress.progress_percent)}%"
                data['assessment.overall_score'] = f"{int(getattr(progress, 'overall_score', 100))}%"
            else:
                data['enrollment.completed_at'] = timezone.now().strftime('%d %b %Y')
                data['enrollment.progress_percent'] = '100%'
                data['assessment.overall_score'] = '100%'

        # 4. Certificate Metadata
        if certificate:
            data['certificate.number'] = certificate.certificate_number
            data['certificate.issue_date'] = certificate.issued_at.strftime('%d %b %Y')
            data['certificate.verification_code'] = certificate.verification_code
            if certificate.completed_at:
                data['certificate.completion_date'] = certificate.completed_at.strftime('%d %b %Y')
        else:
            data['certificate.number'] = custom_overrides.get('certificate.number', 'CS-2026-PREVIEW') if custom_overrides else 'CS-2026-PREVIEW'
            data['certificate.issue_date'] = timezone.now().strftime('%d %b %Y')
            data['certificate.completion_date'] = timezone.now().strftime('%d %b %Y')
            data['certificate.verification_code'] = 'PREVIEW-1234-VERIFY'

        # Apply any manual overrides
        if custom_overrides:
            data.update(custom_overrides)

        return data


class CertificateService:

    @classmethod
    def generate_certificate_number(cls, academy=None) -> str:
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
        while True:
            raw = uuid.uuid4().hex.upper()
            code = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"
            if not Certificate.objects.filter(verification_code=code).exists():
                return code

    @classmethod
    def is_eligible_for_certificate(cls, student, course) -> tuple[bool, str]:
        if not course.certificate_enabled:
            return False, "Certificates are disabled for this course."

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
        certificate_photo=None,
        enrollment=None,
        reissued_from=None,
        **kwargs
    ) -> Certificate:
        existing_cert = Certificate.objects.filter(
            student=student,
            course=course,
            status=CertificateStatus.ISSUED
        ).first()

        if existing_cert:
            return existing_cert

        is_eligible, reason = cls.is_eligible_for_certificate(student, course)
        if not is_eligible:
            raise ValidationError(f"Cannot issue certificate: {reason}")

        enrollment = Enrollment.objects.filter(student=student, course=course).first()

        if not template:
            if hasattr(course, 'certificate_config') and course.certificate_config and course.certificate_config.template:
                template = course.certificate_config.template
            elif course.academy:
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

        resolved_data = CertificateDataResolver.resolve_data(student=student, course=course, enrollment=enrollment)

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

        if not pdf_storage_mode:
            if course.academy and hasattr(course.academy, 'certificate_settings'):
                pdf_storage_mode = course.academy.certificate_settings.default_pdf_storage_mode
            else:
                pdf_storage_mode = CertPDFMode.ON_DEMAND

        cert_num = cls.generate_certificate_number(course.academy)
        ver_code = cls.generate_verification_code()

        progress = CourseProgress.objects.filter(student=student, course=course).first()
        completed_at = progress.completed_at if (progress and progress.completed_at) else timezone.now()

        certificate = Certificate.objects.create(
            student=student,
            course=course,
            enrollment=enrollment,
            template=template,
            certificate_number=cert_num,
            verification_code=ver_code,
            student_name_snapshot=resolved_data.get('student.full_name', ''),
            course_name_snapshot=resolved_data.get('course.title', ''),
            academy_name_snapshot=resolved_data.get('academy.name', 'CubixSkill'),
            custom_data_snapshot=resolved_data,
            issued_at=timezone.now(),
            completed_at=completed_at,
            status=CertificateStatus.ISSUED,
            certificate_photo=certificate_photo,
            template_snapshot=template_snapshot,
            pdf_storage_mode=pdf_storage_mode,
            issued_by=issued_by,
            reissued_from=reissued_from or kwargs.get('reissued_from')
        )

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

        if pdf_storage_mode == CertPDFMode.STORED:
            cls.store_persistent_pdf(certificate)

        return certificate

    @classmethod
    def generate_pdf_bytes_for_certificate(cls, certificate: Certificate) -> bytes:
        resolved_data = certificate.custom_data_snapshot or CertificateDataResolver.resolve_data(
            student=certificate.student,
            course=certificate.course,
            enrollment=certificate.enrollment,
            certificate=certificate
        )

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

        background_media = None
        if certificate.template and certificate.template.background_media:
            background_media = certificate.template.background_media

        student_photo_media = certificate.certificate_photo
        if not student_photo_media and hasattr(certificate.student, 'student_profile'):
            student_photo_media = certificate.student.student_profile.profile_photo

        verification_url = f"/api/v1/certificates/verify/{certificate.verification_code}/"

        return CertificatePDFGenerator.generate_pdf(
            snapshot_data=resolved_data,
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
        pdf_bytes = cls.generate_pdf_bytes_for_certificate(certificate)
        from storage.models import MediaFile, MediaType, MediaStatus
        from storage.services import StorageUsageService

        academy = certificate.course.academy
        filename = f"certificate_{certificate.certificate_number}.pdf"
        relative_path = f"certificates/{filename}"

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
        if certificate.status == CertificateStatus.REVOKED:
            return certificate

        certificate.status = CertificateStatus.REVOKED
        certificate.revoked_at = timezone.now()
        certificate.revoked_by = revoked_by
        certificate.revocation_reason = reason
        certificate.save()

        CertificateIssueLog.objects.create(
            certificate=certificate,
            event_type=IssueLogEventType.REVOKED,
            performed_by=revoked_by,
            reason=reason or "Certificate revoked by administrator"
        )
        return certificate

    @classmethod
    def preview_template(cls, template, sample_data=None) -> bytes:
        snapshot_data = {
            'student.full_name': (sample_data or {}).get('student_name') or 'Sample Student',
            'course.title': (sample_data or {}).get('course_name') or 'Sample Course',
            'academy.name': (sample_data or {}).get('academy_name') or 'CubixSkill Academy',
            'certificate.number': 'CERT-PREVIEW-001',
            'certificate.issue_date': 'August 28, 2026',
        }
        template_data = template.template_data if isinstance(template.template_data, dict) else {}
        return CertificatePDFGenerator.generate_pdf(
            snapshot_data=snapshot_data,
            template_data=template_data,
            orientation=template.orientation or 'LANDSCAPE',
            page_size=template.page_size or 'A4',
            custom_width=template.custom_width,
            custom_height=template.custom_height,
            custom_unit=template.custom_unit,
            background_media=template.background_media,
            show_student_photo=template.show_student_photo,
            student_photo_shape=template.student_photo_shape or 'CIRCLE',
        )

    @classmethod
    def reissue_certificate(cls, certificate, reissued_by=None, reason: str = "Reissued", **kwargs):
        if isinstance(certificate, str):
            certificate = Certificate.objects.get(pk=certificate)
        cls.revoke_certificate(certificate, revoked_by=reissued_by, reason=reason)
        certificate.status = CertificateStatus.REISSUED
        certificate.save()
        return cls.issue_if_eligible(
            student=certificate.student,
            course=certificate.course,
            enrollment=certificate.enrollment,
            issued_by=reissued_by,
            reissued_from=certificate
        )
