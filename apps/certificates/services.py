import logging
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)
from certificates.generator import CertificatePDFGenerator
from certificates.models import (
    Certificate,
    CertificateIssueLog,
    CertificateStatus,
    CertificateTemplate,
    CertPDFMode,
    IssueLogEventType,
)
from enrollments.models import Enrollment
from learning_progress.models import CourseProgress, ProgressStatus
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
        custom_overrides: dict[str, Any] = None
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}

        # 1. Student Fields
        if student:
            if hasattr(student, 'student_profile'):
                user = student
                profile = getattr(student, 'student_profile', None)
            elif hasattr(student, 'user'):
                profile = student
                user = student.user
            else:
                user = student
                profile = None

            full_name = getattr(user, 'full_name', '') if user else ''
            if not full_name and profile:
                full_name = getattr(profile, 'display_name', '')

            data['student.full_name'] = full_name
            data['student.email'] = getattr(user, 'email', '') if user else ''
            data['student.phone'] = getattr(user, 'phone', '') if user else ''
            
            student_code = getattr(profile, 'student_code', '') if profile else ''
            data['student.student_code'] = student_code
            data['student.code'] = student_code

            # Resolve Custom Student Fields
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
                enrolled_dt = getattr(enrollment, 'enrolled_at', None)
                data['enrollment.enrolled_at'] = enrolled_dt.strftime('%d %b %Y') if enrolled_dt else ''
                data['enrollment.status'] = getattr(enrollment, 'status', '')

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
    def ensure_certificate_name_field(cls, academy):
        if not academy:
            return None
        from students.models import StudentCustomFieldDefinition
        cd, _ = StudentCustomFieldDefinition.objects.get_or_create(
            academy=academy,
            key='certificate_name',
            defaults={
                'label': 'Name on Certificate',
                'field_type': 'TEXT',
                'available_for_certificate': True,
                'required': True,
                'is_active': True,
                'sort_order': 0,
            }
        )
        if not cd.available_for_certificate or not cd.is_active or not cd.required:
            cd.available_for_certificate = True
            cd.is_active = True
            cd.required = True
            cd.save(update_fields=['available_for_certificate', 'is_active', 'required'])
        return cd

    @classmethod
    def get_required_student_fields(cls, student, template=None, course=None) -> list[dict]:
        """
        Authoritative helper to discover all required student personal fields
        from assigned certificate template elements and academy custom student fields.
        Returns a list of dicts: [{"key": "...", "label": "...", "required": True, "type": "..."}]
        """
        required_fields = []
        academy = getattr(course, 'academy', None) or getattr(template, 'academy', None)
        if academy:
            cls.ensure_certificate_name_field(academy)

        # 1. Inspect elements in template if available
        if template and template.template_data and isinstance(template.template_data, dict):
            elements = template.template_data.get('elements', [])
            if isinstance(elements, list):
                for el in elements:
                    if isinstance(el, dict):
                        binding = el.get('binding') or el.get('field', '')
                        if binding == 'student.full_name':
                            binding = 'student.custom.certificate_name'
                        if binding and (binding.startswith('student.custom.') or binding.startswith('student.')):
                            if binding != 'student.full_name':
                                label = el.get('label') or binding.replace('.', ' ').replace('_', ' ').title()
                                is_req = bool(el.get('required', False) or binding == 'student.custom.certificate_name')
                                if is_req and not any(f['key'] == binding for f in required_fields):
                                    required_fields.append({
                                        'key': binding,
                                        'label': label if binding != 'student.custom.certificate_name' else 'Name on Certificate',
                                        'required': True,
                                        'type': el.get('type', 'text')
                                    })

        # 2. Inspect Academy custom field definitions that are marked required and available_for_certificate
        if academy:
            from students.models import StudentCustomFieldDefinition
            custom_defs = StudentCustomFieldDefinition.objects.filter(
                academy=academy,
                available_for_certificate=True,
                required=True,
                is_active=True
            ).order_by('sort_order', 'created_at')
            for cd in custom_defs:
                key_name = f"student.custom.{cd.key}"
                if key_name != 'student.full_name' and not any(f['key'] == key_name for f in required_fields):
                    required_fields.append({
                        'key': key_name,
                        'label': cd.label,
                        'required': True,
                        'type': cd.field_type
                    })

        # Ensure student.custom.certificate_name is always present as required field
        if not any(f['key'] == 'student.custom.certificate_name' for f in required_fields):
            required_fields.insert(0, {
                'key': 'student.custom.certificate_name',
                'label': 'Name on Certificate',
                'required': True,
                'type': 'text'
            })

        # Strictly exclude student.full_name from certificate required personal fields
        required_fields = [f for f in required_fields if f['key'] != 'student.full_name']

        return required_fields

    @classmethod
    def check_required_student_fields(cls, student, template=None, course=None) -> list[dict]:
        """
        Validates required student personal fields based on get_required_student_fields.
        Returns a list of missing fields: [{"key": "...", "label": "..."}]
        """
        required_fields = cls.get_required_student_fields(student, template=template, course=course)

        # Resolve student current data
        resolved_data = CertificateDataResolver.resolve_data(student=student, course=course)

        missing = []
        for req in required_fields:
            key = req['key']
            val = resolved_data.get(key, None)
            if val is None or str(val).strip() == '':
                missing.append({'key': key, 'label': req['label']})

        return missing

    @classmethod
    @transaction.atomic
    def issue_or_check_for_enrollment(
        cls,
        enrollment,
        triggered_by: str = "COURSE_COMPLETION",
        issued_by=None
    ) -> dict:
        """
        Canonical backend service method to check eligibility, validate required profile fields,
        deduct certificate credit atomically, issue certificate idempotently, and return structured result.
        """
        student = enrollment.student
        course = enrollment.course
        academy = course.academy

        # 1. Check existing issued certificate
        existing_cert = Certificate.objects.filter(
            enrollment=enrollment,
            status=CertificateStatus.ISSUED
        ).first() or Certificate.objects.filter(
            student=student,
            course=course,
            status=CertificateStatus.ISSUED
        ).first()

        if existing_cert:
            from certificates.serializers import CertificateSerializer
            return {
                "success": True,
                "course_completed": True,
                "certificate_status": "ISSUED",
                "code": "CERTIFICATE_ISSUED",
                "certificate": CertificateSerializer(existing_cert).data,
                "missing_fields": []
            }

        # 2. Check feature flag
        from features.services import CourseFeatureService
        if not course.certificate_enabled or not CourseFeatureService.has_feature(course, 'COMPLETION_CERTIFICATE'):
            return {
                "success": False,
                "course_completed": True,
                "certificate_status": "FEATURE_DISABLED",
                "code": "CERTIFICATE_FEATURE_DISABLED",
                "detail": "Certificate feature is disabled for this course.",
                "missing_fields": []
            }

        # 3. Check course completion status
        is_eligible, reason = cls.is_eligible_for_certificate(student, course)
        if not is_eligible:
            return {
                "success": False,
                "course_completed": False,
                "certificate_status": "NOT_ELIGIBLE",
                "code": "CERTIFICATE_NOT_ELIGIBLE",
                "detail": reason,
                "missing_fields": []
            }

        # 4. Check assigned template
        template = None
        if hasattr(course, 'certificate_config') and course.certificate_config and course.certificate_config.template:
            template = course.certificate_config.template
        elif academy:
            template = CertificateTemplate.objects.filter(
                academy=academy,
                is_default=True,
                is_active=True
            ).first() or CertificateTemplate.objects.filter(
                academy=academy,
                is_active=True
            ).first()

        if not template:
            return {
                "success": False,
                "course_completed": True,
                "certificate_status": "NO_TEMPLATE",
                "code": "CERTIFICATE_NO_TEMPLATE",
                "detail": "No active certificate template is assigned to this course.",
                "missing_fields": []
            }

        # 4b. Precheck template fonts for PDF compatibility BEFORE credit debit
        if template and template.template_data and isinstance(template.template_data, dict):
            elements = template.template_data.get('elements', [])
            if isinstance(elements, list):
                from certificates.selectors import CertificateFontSelector
                available_fonts = CertificateFontSelector.get_available_fonts(academy)
                font_map = {str(f.id): f for f in available_fonts}
                font_key_map = {f.key: f for f in available_fonts}

                for el in elements:
                    if isinstance(el, dict):
                        font_id = str(el.get('fontId') or el.get('font_id') or '')
                        font_key = el.get('fontKey') or el.get('font_key')
                        target_font = font_map.get(font_id) or font_key_map.get(font_key)
                        if target_font and target_font.source == 'ACADEMY' and target_font.pdf_compatible is False:
                            return {
                                "success": False,
                                "course_completed": True,
                                "certificate_status": "FONT_UNSUPPORTED",
                                "code": "CERTIFICATE_TEMPLATE_FONT_INVALID",
                                "detail": f"The assigned certificate template contains custom font '{target_font.name}' which is not PDF-compatible.",
                                "missing_fields": []
                            }

        # 5. Check required student personal fields
        missing_fields = cls.check_required_student_fields(student=student, template=template, course=course)
        if missing_fields:
            return {
                "success": False,
                "course_completed": True,
                "certificate_status": "PROFILE_INCOMPLETE",
                "code": "CERTIFICATE_PROFILE_INCOMPLETE",
                "detail": "Required student personal details are incomplete.",
                "missing_fields": missing_fields
            }

        # 6. Check & Deduct Certificate Credit using central Super Admin pricing
        from control_panel.models import PricingService
        cost_int = PricingService.get_credit_cost('COMPLETION_CERTIFICATE', default_cost=5)
        required_credits = Decimal(str(cost_int))

        if academy:
            from credits.models import (
                CreditAccount,
            )
            from credits.services import CreditsService
            account = CreditsService.get_or_create_account(academy)
            account_locked = CreditAccount.objects.select_for_update().get(id=account.id)

            if account_locked.balance < required_credits:
                formatted_cost = int(required_credits) if required_credits == int(required_credits) else required_credits
                return {
                    "success": False,
                    "course_completed": True,
                    "certificate_status": "PENDING_CREDIT",
                    "code": "CERTIFICATE_CREDIT_INSUFFICIENT",
                    "detail": f"Insufficient academy credits. {formatted_cost} credits are required to issue this certificate.",
                    "missing_fields": []
                }

        # 7. Issue Certificate & Apply Credit Debit Atomically
        certificate = cls.issue_if_eligible(
            student=student,
            course=course,
            issued_by=issued_by,
            template=template,
            enrollment=enrollment
        )

        student_public_url = getattr(settings, 'STUDENT_PUBLIC_URL', 'http://localhost:5174').rstrip('/')
        return {
            "success": True,
            "course_completed": True,
            "certificate_status": "ISSUED",
            "code": "CERTIFICATE_ISSUED",
            "certificate": {
                "id": str(certificate.id),
                "status": certificate.status,
                "certificate_number": certificate.certificate_number,
                "verification_code": certificate.verification_code,
                "issued_at": certificate.issued_at.isoformat(),
                "download_url": f"/api/v1/certificates/student/certificates/{certificate.id}/download/",
                "view_url": f"/api/v1/certificates/student/certificates/{certificate.id}/download/",
                "verification_url": f"{student_public_url}/verify/certificate/{certificate.verification_code}"
            },
            "missing_fields": []
        }

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
        reissued_from=None,
        enrollment=None,
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

        if not enrollment:
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

        # Check required student profile fields before issuing
        missing_fields = cls.check_required_student_fields(student=student, template=template, course=course)
        if missing_fields:
            raise ValidationError(f"Required student personal details are incomplete: {[m['label'] for m in missing_fields]}")

        resolved_data = CertificateDataResolver.resolve_data(student=student, course=course, enrollment=enrollment)

        if template and template.template_data:
            cls.validate_template_text_fit(
                template_data=template.template_data,
                resolved_data=resolved_data,
                orientation=template.orientation,
                page_size=template.page_size,
                custom_width=template.custom_width,
                custom_height=template.custom_height,
                custom_unit=template.custom_unit
            )

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

        # Resolve central pricing cost
        from control_panel.models import PricingService
        cost_int = PricingService.get_credit_cost('COMPLETION_CERTIFICATE', default_cost=5)
        required_credits = Decimal(str(cost_int))

        # Check & lock credit balance
        academy = course.academy
        ledger_entry = None
        if academy:
            from credits.models import CreditAccount, CreditSourceType
            from credits.services import CreditsService
            account = CreditsService.get_or_create_account(academy)
            account_locked = CreditAccount.objects.select_for_update().get(id=account.id)

            if account_locked.balance < required_credits:
                formatted_cost = int(required_credits) if required_credits == int(required_credits) else required_credits
                raise ValidationError(f"Insufficient academy credits. {formatted_cost} credits are required to issue this certificate.")

        certificate = Certificate.objects.create(
            student=student,
            course=course,
            enrollment=enrollment,
            template=template,
            certificate_number=cert_num,
            verification_code=ver_code,
            student_name_snapshot=resolved_data.get('student.custom.certificate_name', ''),
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
            reissued_from=reissued_from or kwargs.get('reissued_from'),
            credits_charged=required_credits,
            credit_charge_applied=True if academy else False,
            credit_charged_at=timezone.now() if academy else None,
        )

        if academy:
            from credits.models import CreditSourceType
            from credits.services import CreditsService
            idempotency_key = f"CERTIFICATE_ISSUE:{certificate.id}"
            ledger_entry = CreditsService.debit(
                academy=academy,
                amount=required_credits,
                source_type=CreditSourceType.CERTIFICATE_ISSUE,
                idempotency_key=idempotency_key,
                description=f"Completion Certificate Issued for {student.email} in {course.title}",
                reference_type="CERTIFICATE",
                reference_id=str(certificate.id),
                created_by=issued_by or student,
                metadata={"course_id": str(course.id), "student_id": str(student.id), "certificate_number": cert_num}
            )
            certificate.credit_ledger_entry = ledger_entry
            certificate.save(update_fields=['credit_ledger_entry'])

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
        if isinstance(resolved_data, dict) and certificate.course and certificate.course.academy_id:
            resolved_data['academy_id'] = str(certificate.course.academy_id)

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

        student_public_url = getattr(settings, 'STUDENT_PUBLIC_URL', 'http://localhost:5174').rstrip('/')
        verification_url = f"{student_public_url}/verify/certificate/{certificate.verification_code}"

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
        from storage.models import MediaFile, MediaStatus, MediaType
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
    def regenerate_pdf_from_snapshot(cls, certificate: Certificate) -> bytes:
        """
        Regenerates stored PDF file from immutable template_snapshot and custom_data_snapshot
        without altering certificate number, verification code, or deducting extra credits.
        """
        pdf_bytes = cls.generate_pdf_bytes_for_certificate(certificate)

        if certificate.pdf_media:
            full_dir = settings.MEDIA_ROOT / "certificates"
            full_dir.mkdir(parents=True, exist_ok=True)
            filename = f"certificate_{certificate.certificate_number}.pdf"
            full_path = full_dir / filename
            with open(full_path, "wb") as f:
                f.write(pdf_bytes)

            certificate.pdf_media.size_bytes = len(pdf_bytes)
            certificate.pdf_media.save(update_fields=['size_bytes'])

            CertificateIssueLog.objects.create(
                certificate=certificate,
                event_type=IssueLogEventType.REISSUED,
                performed_by=certificate.issued_by or certificate.student,
                reason="PDF regenerated from immutable snapshot",
                metadata={'regenerated_pdf': True}
            )

        return pdf_bytes

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
        student_public_url = getattr(settings, 'STUDENT_PUBLIC_URL', 'http://localhost:5174').rstrip('/')
        preview_verification_url = f"{student_public_url}/verify/certificate/PREVIEW-DEMO"

        snapshot_data = {
            'student.custom.certificate_name': (sample_data or {}).get('student_name') or 'Muhammed Ashraf Al Farooqi (Preview)',
            'student.full_name': (sample_data or {}).get('student_name') or 'Muhammed Ashraf Al Farooqi (Preview)',
            'course.title': (sample_data or {}).get('course_name') or 'Sample Course Completion Certificate Preview',
            'academy.name': (sample_data or {}).get('academy_name') or 'CubixSkill Academy',
            'certificate.number': 'CS-2026-PREVIEW',
            'certificate.issue_date': 'August 28, 2026',
            'certificate.verification_url': preview_verification_url,
            'academy_id': str(template.academy.id) if template and template.academy else None,
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
            verification_url=preview_verification_url,
        )

    @classmethod
    def validate_template_text_fit(cls, template_data: dict, resolved_data: dict, orientation='LANDSCAPE', page_size='A4', custom_width=None, custom_height=None, custom_unit=None):
        if not template_data or not isinstance(template_data, dict):
            return

        elements = template_data.get('elements', [])
        if not elements and isinstance(template_data, list):
            elements = template_data

        if not elements:
            return

        from certificates.generator import resolve_page_size, resolve_reportlab_font
        page_w, page_h = resolve_page_size(page_size=page_size, custom_width=custom_width, custom_height=custom_height, custom_unit=custom_unit, orientation=orientation)

        import io

        from reportlab.pdfgen import canvas
        dummy_buf = io.BytesIO()
        c = canvas.Canvas(dummy_buf, pagesize=(page_w, page_h))

        for item in elements:
            if not isinstance(item, dict):
                continue

            binding = item.get('binding') or item.get('field', '')
            text_value = item.get('text', '')
            prefix = item.get('prefix', '')
            suffix = item.get('suffix', '')

            if binding and binding != 'static':
                val = resolved_data.get(binding, '')
                text_value = f"{prefix}{val}{suffix}".strip() if val != '' else ''
            elif text_value:
                for k, v in resolved_data.items():
                    if isinstance(text_value, str) and f"{{{{{k}}}}}" in text_value:
                        text_value = text_value.replace(f"{{{{{k}}}}}", str(v))
                text_value = f"{prefix}{text_value}{suffix}".strip()

            if not text_value:
                continue

            raw_w = item.get('width', 0.8)
            raw_h = item.get('height', 0.08)
            container_w = float(raw_w) * page_w if isinstance(raw_w, (int, float)) and 0 <= raw_w <= 1 else float(raw_w)
            container_h = float(raw_h) * page_h if isinstance(raw_h, (int, float)) and 0 <= raw_h <= 1 else float(raw_h)

            padding_cfg = item.get('padding') or {}
            pad_l = float(padding_cfg.get('left', 2)) if isinstance(padding_cfg, dict) else 2.0
            pad_r = float(padding_cfg.get('right', 2)) if isinstance(padding_cfg, dict) else 2.0
            pad_t = float(padding_cfg.get('top', 1)) if isinstance(padding_cfg, dict) else 1.0
            pad_b = float(padding_cfg.get('bottom', 1)) if isinstance(padding_cfg, dict) else 1.0

            avail_w = max(1.0, container_w - (pad_l + pad_r))
            avail_h = max(1.0, container_h - (pad_t + pad_b))

            configured_min = item.get('minFontSize') or item.get('min_font_size')
            min_font_size = float(configured_min) if configured_min is not None else 12.0

            raw_font = (
                item.get('fontId')
                or item.get('font_id')
                or item.get('fontKey')
                or item.get('font_key')
                or item.get('fontFamily')
                or item.get('font_family')
                or 'Inter'
            )
            font_weight = str(item.get('font_weight', item.get('fontWeight', 'normal'))).lower()
            
            academy_obj = None
            if resolved_data and isinstance(resolved_data, dict):
                acad_id = resolved_data.get('academy_id') or resolved_data.get('academy.id')
                if acad_id:
                    from academy.models import Academy
                    try:
                        academy_obj = Academy.objects.filter(id=acad_id).first()
                    except Exception:
                        pass

            font_name = resolve_reportlab_font(raw_font, font_weight, academy=academy_obj)

            is_multiline = bool(item.get('multiline', False))
            line_height = float(item.get('lineHeight') or item.get('line_height') or 1.0)

            fits_at_min = False
            if not is_multiline:
                string_w = c.stringWidth(text_value, font_name, min_font_size)
                string_h = min_font_size * line_height
                fits_at_min = (string_w <= avail_w and string_h <= avail_h)
            else:
                words = text_value.split()
                if not words:
                    fits_at_min = True
                else:
                    lines = 1
                    cur_w = 0.0
                    space_w = c.stringWidth(" ", font_name, min_font_size)
                    for word in words:
                        word_w = c.stringWidth(word, font_name, min_font_size)
                        if word_w > avail_w:
                            fits_at_min = False
                            break
                        if cur_w == 0.0:
                            cur_w = word_w
                        elif cur_w + space_w + word_w <= avail_w:
                            cur_w += space_w + word_w
                        else:
                            lines += 1
                            cur_w = word_w
                    else:
                        tot_h = lines * min_font_size * line_height
                        fits_at_min = (tot_h <= avail_h)

            if not fits_at_min:
                field_key = binding or 'text'
                label_name = item.get('label') or field_key.replace('.', ' ').replace('_', ' ').title()
                raise ValidationError({
                    'code': 'CERTIFICATE_FIELD_TEXT_TOO_LONG',
                    'field': field_key,
                    'label': label_name,
                    'message': f"{label_name} is too long for the configured certificate field."
                })

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
