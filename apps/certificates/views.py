import logging
import os

from django.db import models
from django.http import HttpResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from certificates.models import (
    Certificate,
    CertificateFont,
    CertificateIssueLog,
    CertificateTemplate,
    FontSourceChoices,
)
from certificates.selectors import CertificateFontSelector, CertificateSelector
from certificates.serializers import (
    CertificateFontSerializer,
    CertificateFontUploadSerializer,
    CertificateSerializer,
    CertificateSettingsSerializer,
    CertificateTemplateSerializer,
    ManualIssueCertificateSerializer,
    PublicVerificationSerializer,
    ReissueCertificateSerializer,
    RevokeCertificateSerializer,
    StudentCertificateListSerializer,
    TemplatePreviewSerializer,
)
from certificates.services import CertificateDataResolver, CertificateService
from courses.models import Course

#--------------------------------------------------------------
# EnrollmentIssueOrCheckCertificateView
#--------------------------------------------------------------
from enrollments.models import Enrollment
from rest_framework.exceptions import ValidationError
from storage.models import MediaFile
from users_roles.models import User


class EnrollmentIssueOrCheckCertificateView(APIView):
    """
    Canonical endpoint for students to trigger or re-check certificate issuance for an enrollment.
    POST /api/v1/certificates/enrollments/<enrollment_uuid>/issue-or-check/
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, enrollment_uuid: str):
        try:
            enrollment = Enrollment.objects.select_related('student', 'course', 'course__academy').get(
                id=enrollment_uuid,
                student=request.user
            )
        except (Enrollment.DoesNotExist, ValueError):
            return Response(
                {"detail": "Enrollment not found or does not belong to you."},
                status=status.HTTP_404_NOT_FOUND
            )

        res = CertificateService.issue_or_check_for_enrollment(
            enrollment=enrollment,
            triggered_by="STUDENT_RECHECK",
            issued_by=request.user
        )
        return Response(res, status=status.HTTP_200_OK)


from django.db import transaction
from students.models import StudentCustomFieldDefinition, StudentCustomFieldValue


class EnrollmentCertificateProfileDetailsView(APIView):
    """
    Canonical API for authenticated student to load & save certificate personal details required for an enrollment.
    GET /api/v1/certificates/enrollments/<enrollment_uuid>/profile-details/
    PATCH /api/v1/certificates/enrollments/<enrollment_uuid>/profile-details/
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_enrollment(self, request, enrollment_uuid: str):
        try:
            return Enrollment.objects.select_related('student', 'course', 'course__academy').get(
                id=enrollment_uuid,
                student=request.user
            )
        except (Enrollment.DoesNotExist, ValueError):
            return None

    def _get_assigned_template(self, course):
        if getattr(course, 'certificate_template', None):
            return course.certificate_template
        return CertificateTemplate.objects.filter(academy=course.academy, is_default=True, is_active=True).first()

    def get(self, request, enrollment_uuid: str):
        enrollment = self._get_enrollment(request, enrollment_uuid)
        if not enrollment:
            return Response({"detail": "Enrollment not found or does not belong to you."}, status=status.HTTP_404_NOT_FOUND)

        course = enrollment.course
        template = self._get_assigned_template(course)
        student = request.user

        required_defs = CertificateService.get_required_student_fields(student, template=template, course=course)
        resolved_data = CertificateDataResolver.resolve_data(student=student, course=course, enrollment=enrollment)

        fields = []
        missing_fields = []

        for req in required_defs:
            key = req['key']
            label = req['label']
            is_required = req.get('required', True)
            field_type = req.get('type', 'text').lower()

            editable = True
            if key in ['student.email', 'student.student_code', 'student.code']:
                editable = False

            val = resolved_data.get(key, '')
            is_missing = is_required and (val is None or str(val).strip() == '')

            if is_missing:
                missing_fields.append({"key": key, "label": label})

            fields.append({
                "key": key,
                "label": label,
                "type": field_type if field_type in ['text', 'textarea', 'number', 'date', 'email', 'phone'] else 'text',
                "required": is_required,
                "editable": editable,
                "value": val if val is not None else '',
                "missing": is_missing
            })

        cert = Certificate.objects.filter(enrollment=enrollment).first()
        cert_status = cert.status if cert else ("PROFILE_INCOMPLETE" if missing_fields else "NOT_ISSUED")

        return Response({
            "enrollment_id": str(enrollment.id),
            "course_id": str(course.id),
            "certificate_status": cert_status,
            "fields": fields,
            "missing_fields": missing_fields
        }, status=status.HTTP_200_OK)

    def patch(self, request, enrollment_uuid: str):
        enrollment = self._get_enrollment(request, enrollment_uuid)
        if not enrollment:
            return Response({"detail": "Enrollment not found or does not belong to you."}, status=status.HTTP_404_NOT_FOUND)

        course = enrollment.course
        template = self._get_assigned_template(course)
        student = request.user
        profile = getattr(student, 'student_profile', None)

        payload_values = request.data.get('values', {})
        if not isinstance(payload_values, dict):
            return Response({
                "code": "INVALID_PAYLOAD",
                "detail": "Expected 'values' dictionary object in payload."
            }, status=status.HTTP_400_BAD_REQUEST)

        CertificateService.ensure_certificate_name_field(course.academy)
        required_defs = CertificateService.get_required_student_fields(student, template=template, course=course)
        valid_keys = {req['key']: req for req in required_defs}

        # Include all active certificate custom fields for this academy in valid_keys
        from students.models import StudentCustomFieldDefinition
        custom_defs = StudentCustomFieldDefinition.objects.filter(
            academy=course.academy,
            available_for_certificate=True,
            is_active=True
        )
        for cd in custom_defs:
            key_name = f"student.custom.{cd.key}"
            if key_name not in valid_keys:
                valid_keys[key_name] = {'key': key_name, 'label': cd.label, 'required': cd.required}

        errors = {}

        # Validate submitted keys
        for key, value in payload_values.items():
            if key not in valid_keys:
                return Response({
                    "code": "UNAUTHORIZED_FIELD_KEY",
                    "detail": f"Field '{key}' is not an allowed certificate detail field for this enrollment."
                }, status=status.HTTP_400_BAD_REQUEST)

            if key in ['student.email', 'student.student_code', 'student.code']:
                return Response({
                    "code": "READ_ONLY_FIELD",
                    "detail": f"Field '{key}' is read-only and cannot be updated."
                }, status=status.HTTP_400_BAD_REQUEST)

        # Check required fields
        for req in required_defs:
            key = req['key']
            if req.get('required', False) and key not in ['student.email', 'student.student_code', 'student.code']:
                val = payload_values.get(key, None)
                if val is None:
                    current_val = CertificateDataResolver.resolve_data(student=student, course=course).get(key, '')
                    if not current_val or str(current_val).strip() == '':
                        errors[key] = [f"{req['label']} is required."]
                elif str(val).strip() == '':
                    errors[key] = [f"{req['label']} is required."]

        # Validate Certificate Name if provided
        if 'student.custom.certificate_name' in payload_values:
            cn_val = str(payload_values['student.custom.certificate_name']).strip()
            if not cn_val:
                errors['student.custom.certificate_name'] = ["Name on Certificate cannot be blank."]

        if errors:
            return Response({
                "code": "CERTIFICATE_PROFILE_VALIDATION_ERROR",
                "detail": "Please complete the required certificate details.",
                "errors": errors
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Update ONLY Custom Fields for student profile (Zero effect on User.full_name / StudentProfile.display_name)
            if profile:
                for key, value in payload_values.items():
                    if key.startswith('student.custom.'):
                        custom_key = key.replace('student.custom.', '')
                        cd = StudentCustomFieldDefinition.objects.filter(
                            academy=course.academy,
                            key=custom_key,
                            available_for_certificate=True,
                            is_active=True
                        ).first()
                        if not cd and custom_key == 'certificate_name':
                            cd = CertificateService.ensure_certificate_name_field(course.academy)

                        if cd:
                            StudentCustomFieldValue.objects.update_or_create(
                                student=profile,
                                field_definition=cd,
                                defaults={"value": str(value or '').strip()}
                            )

        # Return updated state
        return self.get(request, enrollment_uuid)


#--------------------------------------------------------------
# PublicCertificateVerifyView
#--------------------------------------------------------------

class PublicCertificateVerifyView(APIView):
    """
    Public endpoint for verifying certificates via verification code.
    No authentication required.
    GET /api/v1/certificates/verify/{verification_code}/
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, verification_code: str):
        data = CertificateSelector.get_public_verification_data(verification_code)
        if not data:
            return Response(
                {"detail": "Invalid or unknown certificate verification code."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = PublicVerificationSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# CertificateTemplateBindingsView
#--------------------------------------------------------------


from certificates.discovery import CertificateFieldDiscoveryService


class CertificateTemplateBindingsView(APIView):
    """
    Returns available dynamic bindings for the Certificate Designer.
    GET /api/v1/certificates/template-bindings/?course_id=UUID
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        academy = getattr(user, 'academy', None)
        course_id = request.query_params.get('course_id')

        if course_id:
            bindings = CertificateFieldDiscoveryService.get_available_fields_for_course(course_id, academy=academy)
            return Response(bindings, status=status.HTTP_200_OK)

        bindings = [
            {"key": "student.custom.certificate_name", "label": "Name on Certificate", "group": "Personal Details", "type": "text"},
            {"key": "student.full_name", "label": "Student Profile Name", "group": "Student", "type": "text"},
            {"key": "student.student_code", "label": "Student ID", "group": "Student", "type": "text"},
            {"key": "student.email", "label": "Student Email", "group": "Student", "type": "text"},
            {"key": "course.title", "label": "Course Name", "group": "Course", "type": "text"},
            {"key": "course.code", "label": "Course Code", "group": "Course", "type": "text"},
            {"key": "academy.name", "label": "Academy Name", "group": "Academy", "type": "text"},
            {"key": "certificate.number", "label": "Certificate Number", "group": "Certificate", "type": "text"},
            {"key": "certificate.issue_date", "label": "Issue Date", "group": "Certificate", "type": "text"},
            {"key": "certificate.completion_date", "label": "Completion Date", "group": "Certificate", "type": "text"},
        ]

        if academy:
            custom_fields = StudentCustomFieldDefinition.objects.filter(
                academy=academy,
                available_for_certificate=True,
                is_active=True
            )
            for cf in custom_fields:
                bindings.append({
                    "key": f"student.custom.{cf.key}",
                    "label": f"Student {cf.label}",
                    "group": "Personal Details",
                    "type": "text"
                })

        return Response(bindings, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# StudentCertificateViewSet
#--------------------------------------------------------------

class StudentCertificateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Endpoints for students to view and download their own issued certificates.
    GET /api/v1/student/certificates/
    GET /api/v1/student/certificates/{id}/
    GET /api/v1/student/certificates/{id}/download/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CertificateSelector.get_student_certificates(self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return StudentCertificateListSerializer
        return CertificateSerializer

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        certificate = self.get_object()

        # Log download action
        CertificateIssueLog.objects.create(
            certificate=certificate,
            event_type='DOWNLOADED',
            performed_by=request.user,
            reason="Student downloaded certificate PDF"
        )

        pdf_bytes = CertificateService.generate_pdf_bytes_for_certificate(certificate)
        filename = f"certificate_{certificate.certificate_number}.pdf"

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

#--------------------------------------------------------------
# CertificateTemplateViewSet
#--------------------------------------------------------------

class CertificateTemplateViewSet(viewsets.ModelViewSet):
    """
    Academy staff API to manage certificate templates.
    GET /api/v1/certificate-templates/
    POST /api/v1/certificate-templates/
    GET /api/v1/certificate-templates/{id}/
    PATCH /api/v1/certificate-templates/{id}/
    DELETE /api/v1/certificate-templates/{id}/
    POST /api/v1/certificate-templates/{id}/preview/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CertificateTemplateSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'academy') and user.academy:
            return CertificateSelector.get_academy_templates(user.academy)
        return CertificateTemplate.objects.none()

    def perform_create(self, serializer):
        from django.db import transaction
        from certificates.models import CourseCertificateConfig
        user = self.request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User is not associated with an Academy.")

        template_data = self.request.data.get('template_data', {})
        if isinstance(template_data, str):
            import json
            try:
                template_data = json.loads(template_data)
            except Exception:
                template_data = {}
        course_id = self.request.data.get('course_id') or template_data.get('selected_course_id')

        with transaction.atomic():
            if course_id:
                existing_config = CourseCertificateConfig.objects.select_for_update().filter(
                    course_id=course_id,
                    course__academy=academy,
                    template__is_active=True
                ).first()
                if existing_config and existing_config.template:
                    raise ValidationError({
                        "detail": "Only one certificate template is allowed per course. Delete or edit the existing template for this course.",
                        "existing_template_id": str(existing_config.template.id),
                        "code": "TEMPLATE_EXISTS"
                    })
            
            template = serializer.save(academy=academy)
            if course_id:
                from courses.models import Course
                course = Course.objects.filter(id=course_id, academy=academy).first()
                if course:
                    config, _ = CourseCertificateConfig.objects.get_or_create(course=course)
                    config.template = template
                    config.is_enabled = True
                    config.save()

    def perform_update(self, serializer):
        from django.db import transaction
        from certificates.models import CourseCertificateConfig
        user = self.request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User is not associated with an Academy.")

        template_data = self.request.data.get('template_data', {})
        if isinstance(template_data, str):
            import json
            try:
                template_data = json.loads(template_data)
            except Exception:
                template_data = {}
        course_id = self.request.data.get('course_id') or template_data.get('selected_course_id')

        with transaction.atomic():
            if course_id:
                existing_config = CourseCertificateConfig.objects.select_for_update().filter(
                    course_id=course_id,
                    course__academy=academy,
                    template__is_active=True
                ).exclude(template_id=serializer.instance.id).first()
                if existing_config and existing_config.template:
                    raise ValidationError({
                        "detail": "Only one certificate template is allowed per course. Delete or edit the existing template for this course.",
                        "existing_template_id": str(existing_config.template.id),
                        "code": "TEMPLATE_EXISTS"
                    })
            
            template = serializer.save()
            if course_id:
                from courses.models import Course
                course = Course.objects.filter(id=course_id, academy=academy).first()
                if course:
                    CourseCertificateConfig.objects.filter(template=template).exclude(course=course).update(template=None)
                    config, _ = CourseCertificateConfig.objects.get_or_create(course=course)
                    config.template = template
                    config.is_enabled = True
                    config.save()

    @action(detail=False, methods=['get'], url_path=r'by-slug/(?P<slug>[\w-]+)')
    def by_slug(self, request, slug=None):
        template = self.get_queryset().filter(slug=slug).first()
        if not template:
            return Response(
                {"detail": "Certificate template not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(template)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        has_issued = template.issued_certificates.exists()
        if has_issued:
            # Soft delete / deactivate to preserve historical issued certificate snapshots
            template.is_active = False
            template.save()
            return Response(
                {"code": "TEMPLATE_IN_USE", "message": "Certificate template has been deactivated because it was used to issue certificates."},
                status=status.HTTP_200_OK
            )
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        template = self.get_object()
        serializer = TemplatePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sample_data = {
            'student_name': serializer.validated_data.get('sample_student_name'),
            'course_name': serializer.validated_data.get('sample_course_name'),
            'academy_name': serializer.validated_data.get('sample_academy_name'),
        }

        pdf_bytes = CertificateService.preview_template(template, sample_data=sample_data)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="template_preview.pdf"'
        return response

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        template = self.get_object()
        from certificates.models import CertificateTemplateVersion
        latest_version = template.versions.order_by('-version_number').first()
        next_ver_num = (latest_version.version_number + 1) if latest_version else 1

        version = CertificateTemplateVersion.objects.create(
            template=template,
            version_number=next_ver_num,
            background_media=template.background_media,
            canvas_width=template.custom_width or 1600.0,
            canvas_height=template.custom_height or 1131.0,
            layout_json=template.template_data.get('elements', []) if isinstance(template.template_data, dict) else [],
            created_by=request.user
        )
        return Response({
            "message": f"Published version {version.version_number} successfully.",
            "version_number": version.version_number
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        from django.db import transaction
        from certificates.models import CourseCertificateConfig
        template = self.get_object()

        course_id = request.data.get('course_id') or (template.template_data.get('selected_course_id') if isinstance(template.template_data, dict) else None)

        with transaction.atomic():
            if course_id:
                existing_config = CourseCertificateConfig.objects.select_for_update().filter(
                    course_id=course_id,
                    course__academy=template.academy,
                    template__is_active=True
                ).first()
                if existing_config and existing_config.template:
                    raise ValidationError("Only one certificate template is allowed per course. Delete or edit the existing template for this course.")

            new_template = CertificateTemplate.objects.create(
                academy=template.academy,
                name=f"{template.name} (Copy)",
                description=template.description,
                template_data=template.template_data,
                orientation=template.orientation,
                page_size=template.page_size,
                background_media=template.background_media,
                show_student_photo=template.show_student_photo,
                student_photo_shape=template.student_photo_shape
            )
            serializer = self.get_serializer(new_template)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='assign-course')
    def assign_course(self, request, pk=None):
        template = self.get_object()
        course_id = request.data.get('course_id')
        if not course_id:
            raise ValidationError({"course_id": "Course ID is required."})

        from certificates.models import CourseCertificateConfig
        from courses.models import Course

        course = Course.objects.filter(id=course_id, academy=template.academy).first()
        if not course:
            raise ValidationError({"course_id": "Course not found in this Academy."})

        config, _ = CourseCertificateConfig.objects.get_or_create(course=course)
        config.template = template
        config.auto_issue = request.data.get('auto_issue', True)
        config.save()

        return Response({"message": f"Template assigned to course '{course.title}'."}, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# CertificateViewSet
#--------------------------------------------------------------

from core.utils import StandardPagination


class CertificateViewSet(viewsets.ModelViewSet):
    """
    Academy staff API to manage issued certificates.
    GET /api/v1/certificates/
    GET /api/v1/certificates/{id}/
    POST /api/v1/certificates/issue/
    POST /api/v1/certificates/{id}/revoke/
    POST /api/v1/certificates/{id}/reissue/
    GET /api/v1/certificates/{id}/download/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CertificateSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'academy') and user.academy:
            return CertificateSelector.get_academy_certificates(
                academy=user.academy,
                search=self.request.query_params.get('search'),
                status_filter=self.request.query_params.get('status'),
                course_id=self.request.query_params.get('course') or self.request.query_params.get('course_id'),
                ordering=self.request.query_params.get('ordering') or self.request.query_params.get('sort_by')
            )
        return Certificate.objects.none()

    @action(detail=False, methods=['get'])
    def summary(self, request):
        user = request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            return Response({})
        metrics = CertificateSelector.get_dashboard_metrics(academy)
        return Response(metrics, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def issue(self, request):
        serializer = ManualIssueCertificateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an academy to issue certificates.")

        student_id = serializer.validated_data['student_id']
        course_id = serializer.validated_data['course_id']
        template_id = serializer.validated_data.get('template_id')
        pdf_storage_mode = serializer.validated_data.get('pdf_storage_mode')
        cert_photo_id = serializer.validated_data.get('certificate_photo_id')

        try:
            student = User.objects.get(id=student_id)
        except User.DoesNotExist:
            raise ValidationError("Student user not found.")

        try:
            course = Course.objects.get(id=course_id, academy=academy)
        except Course.DoesNotExist:
            raise ValidationError("Course not found or does not belong to your academy.")

        template = None
        if template_id:
            try:
                template = CertificateTemplate.objects.get(id=template_id, academy=academy)
            except CertificateTemplate.DoesNotExist:
                raise ValidationError("Template not found or does not belong to your academy.")

        cert_photo = None
        if cert_photo_id:
            cert_photo = MediaFile.objects.filter(id=cert_photo_id).first()

        certificate = CertificateService.issue_if_eligible(
            student=student,
            course=course,
            issued_by=request.user,
            template=template,
            pdf_storage_mode=pdf_storage_mode,
            certificate_photo=cert_photo
        )

        return Response(
            CertificateSerializer(certificate).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        certificate = self.get_object()
        serializer = RevokeCertificateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('reason', '')
        revoked_cert = CertificateService.revoke_certificate(
            certificate=certificate,
            revoked_by=request.user,
            reason=reason
        )

        return Response(CertificateSerializer(revoked_cert).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reissue(self, request, pk=None):
        certificate = self.get_object()
        serializer = ReissueCertificateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('reason', '')
        template_id = serializer.validated_data.get('template_id')

        new_template = None
        if template_id:
            try:
                new_template = CertificateTemplate.objects.get(
                    id=template_id,
                    academy=request.user.academy
                )
            except CertificateTemplate.DoesNotExist:
                raise ValidationError("Specified new template not found.")

        new_cert = CertificateService.reissue_certificate(
            certificate=certificate,
            reissued_by=request.user,
            reason=reason,
            new_template=new_template
        )

        return Response(CertificateSerializer(new_cert).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        certificate = self.get_object()

        pdf_bytes = CertificateService.generate_pdf_bytes_for_certificate(certificate)
        filename = f"certificate_{certificate.certificate_number}.pdf"

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

#--------------------------------------------------------------
# CertificateSettingsView
#--------------------------------------------------------------

class CertificateSettingsView(APIView):
    """
    API view to retrieve and update Academy certificate settings.
    GET /api/v1/certificate-settings/
    PATCH /api/v1/certificate-settings/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User does not belong to an academy.")

        settings_obj = CertificateSelector.get_or_create_academy_settings(academy)
        serializer = CertificateSettingsSerializer(settings_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User does not belong to an academy.")

        settings_obj = CertificateSelector.get_or_create_academy_settings(academy)
        serializer = CertificateSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# CertificateFontViewSet
#--------------------------------------------------------------

class CertificateFontViewSet(viewsets.ModelViewSet):
    """
    API viewset to list, upload, and manage certificate fonts.
    GET /api/v1/certificates/fonts/
    POST /api/v1/certificates/fonts/upload/
    DELETE /api/v1/certificates/fonts/{id}/
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = CertificateFontSerializer

    def get_queryset(self):
        user = self.request.user
        academy = getattr(user, 'academy', None)
        return CertificateFontSelector.get_available_fonts(academy)

    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an academy to upload custom fonts.")

        serializer = CertificateFontUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        font_file = serializer.validated_data['font_file']
        display_name = serializer.validated_data['display_name']
        user_rights_confirmed = serializer.validated_data['user_rights_confirmed']

        # 1. Save temporary file to perform CertificateFontValidator inspection
        import tempfile
        import uuid

        from certificates.font_validator import CertificateFontValidator
        from storage.services import StorageService

        font_file.seek(0)
        raw_ext = (font_file.name.split('.')[-1] if '.' in font_file.name else 'bin').lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{raw_ext}") as tmp:
            for chunk in font_file.chunks() if hasattr(font_file, 'chunks') else [font_file.read()]:
                tmp.write(chunk)
            tmp_path = tmp.name
        font_file.seek(0)

        font_id = uuid.uuid4()
        val_res = CertificateFontValidator.inspect_and_validate_font(tmp_path, str(font_id))

        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        if not val_res.is_pdf_compatible or not val_res.is_valid:
            raise ValidationError({
                "code": "CERTIFICATE_FONT_UNSUPPORTED",
                "detail": val_res.error_message or "This font cannot be embedded in generated certificate PDFs. Please upload a TrueType-outline TTF or compatible OpenType font."
            })

        font_ext = val_res.format_ext
        outline_type = val_res.outline_type
        mime_type = getattr(font_file, 'content_type', None) or 'font/ttf'

        # Upload using dedicated fonts storage directory
        media = StorageService.upload_media_direct(
            academy_uuid=academy.id,
            user_uuid=request.user.id,
            file_obj=font_file,
            original_filename=f"{font_id}.{font_ext.lower()}",
            mime_type=mime_type,
            file_size_bytes=font_file.size,
            course_uuid=None,
            lesson_uuid=None
        )

        font_key = f"cubix-font-{font_id}"
        resolved_file_url = getattr(media, 'file_url', '') or (f"/media/{media.storage_key}" if getattr(media, 'storage_key', None) else f"/media/{media.stored_filename}")

        try:
            font = CertificateFont.objects.create(
                id=font_id,
                academy=academy,
                key=font_key,
                name=display_name,
                family=display_name,
                format=font_ext,
                outline_type=outline_type,
                pdf_compatible=True,
                weight='400',
                style='normal',
                size_bytes=font_file.size,
                source=FontSourceChoices.ACADEMY,
                user_rights_confirmed=user_rights_confirmed,
                media_file=media,
                file_url=resolved_file_url,
                font_weight_variants=['400', '700'],
                is_active=True,
                is_certificate_safe=True,
                created_by=request.user
            )
        except Exception as err:
            try:
                if hasattr(StorageService, 'delete_media_file'):
                    StorageService.delete_media_file(media.id)
                else:
                    media.delete()
            except Exception:
                pass
            raise err

        return Response(CertificateFontSerializer(font).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        font = self.get_object()
        academy = getattr(request.user, 'academy', None)
        if font.source != FontSourceChoices.ACADEMY or (academy and font.academy_id != academy.id):
            raise ValidationError("You cannot delete this font.")

        from certificates.models import CertificateTemplate
        font_id_str = str(font.id)
        in_use = CertificateTemplate.objects.filter(
            models.Q(template_data__icontains=font.key) | models.Q(template_data__icontains=font_id_str)
        ).exists()

        if in_use:
            font.is_active = False
            font.save()
            return Response(
                {"code": "FONT_IN_USE", "message": "Font deactivated because it is referenced in existing templates."},
                status=status.HTTP_200_OK
            )

        if font.media_file:
            try:
                from storage.services import StorageService
                if hasattr(StorageService, 'delete_media_file'):
                    StorageService.delete_media_file(font.media_file.id)
                else:
                    font.media_file.delete()
            except Exception as e:
                logger.warning(f"Failed to delete font media file on font destroy: {e}")

        font.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
