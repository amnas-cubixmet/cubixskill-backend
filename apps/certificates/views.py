from django.http import HttpResponse
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from rest_framework.exceptions import ValidationError
from users_roles.models import User
from courses.models import Course
from storage.models import MediaFile

from certificates.models import Certificate, CertificateTemplate, CertificateIssueLog, CertPDFMode, CertificateFont, FontSourceChoices
from certificates.selectors import CertificateSelector, CertificateFontSelector
from certificates.services import CertificateService
from certificates.serializers import (
    CertificateTemplateSerializer,
    CertificateSerializer,
    StudentCertificateListSerializer,
    PublicVerificationSerializer,
    ManualIssueCertificateSerializer,
    RevokeCertificateSerializer,
    ReissueCertificateSerializer,
    TemplatePreviewSerializer,
    CertificateSettingsSerializer,
    CertificateFontSerializer,
    CertificateFontUploadSerializer,
)

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

from students.models import StudentCustomFieldDefinition

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
            {"key": "student.full_name", "label": "Student Name", "group": "Student", "type": "text"},
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
        user = self.request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User is not associated with an Academy.")
        serializer.save(academy=academy)

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
        template = self.get_object()
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

        from courses.models import Course
        from certificates.models import CourseCertificateConfig

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

        import uuid
        from storage.services import StorageService

        mime_type = getattr(font_file, 'content_type', None) or 'application/octet-stream'

        media = StorageService.upload_media_direct(
            academy_uuid=academy.id,
            user_uuid=request.user.id,
            file_obj=font_file,
            original_filename=font_file.name,
            mime_type=mime_type,
            file_size_bytes=font_file.size,
            course_uuid=None,
            lesson_uuid=None
        )

        font_key = f"custom_{academy.id}_{uuid.uuid4().hex[:8]}"
        resolved_file_url = getattr(media, 'file_url', '') or getattr(media, 'relative_path', '') or f"/media/{media.stored_filename}"

        try:
            font = CertificateFont.objects.create(
                academy=academy,
                key=font_key,
                name=display_name,
                family=display_name,
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
