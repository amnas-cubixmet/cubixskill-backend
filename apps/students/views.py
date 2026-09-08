import logging
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from students.models import  StudentGuardian, StudentDocument, StudentNote, StudentTag, StudentStatus
from students.selectors import StudentSelector
from students.services import StudentService
from students.serializers import (
    StudentProfileSerializer, StudentCreateSerializer, StudentUpdateSerializer, StudentSelfUpdateSerializer,
    StudentGuardianSerializer, StudentDocumentSerializer, StudentNoteSerializer, StudentTagSerializer
)
from core.permissions import CanAccessAcademyPermission
from core.utils import CubixSkillAPIException, api_response

logger = logging.getLogger(__name__)

#--------------------------------------------------------------
# Student Admin ViewSet
#--------------------------------------------------------------

class StudentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = StudentProfileSerializer

    def get_queryset(self):
        search_query = self.request.query_params.get('search')
        status_filter = self.request.query_params.get('status')
        course_id = self.request.query_params.get('course') or self.request.query_params.get('course_id')
        ordering = self.request.query_params.get('ordering') or self.request.query_params.get('sort_by')
        return StudentSelector.get_academy_students(
            user=self.request.user,
            search_query=search_query,
            status_filter=status_filter,
            course_id=course_id,
            ordering=ordering
        )

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except Exception as exc:
            academy_id = getattr(getattr(request.user, 'academy', None), 'id', None)
            logger.exception(
                "Failed to list students academy=%s page=%s page_size=%s sort_by=%s",
                academy_id,
                request.query_params.get("page"),
                request.query_params.get("page_size"),
                request.query_params.get("sort_by"),
            )
            raise exc

    def create(self, request, *args, **kwargs):
        serializer = StudentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student = StudentService.create_student(
            academy=request.user.academy,
            email=data['email'],
            full_name=data['full_name'],
            phone=data.get('phone', ''),
            created_by=request.user
        )
        if data.get('date_of_birth') or data.get('bio') or (data.get('status') and data['status'] != 'ACTIVE'):
            student = StudentService.update_student(
                student,
                date_of_birth=data.get('date_of_birth'),
                bio=data.get('bio', ''),
                status=data.get('status')
            )

        return api_response(
            data=StudentProfileSerializer(student).data,
            message="Student profile created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        student = self.get_object()
        serializer = StudentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        updated_student = StudentService.update_student(student, **serializer.validated_data)
        return api_response(
            data=StudentProfileSerializer(updated_student).data,
            message="Student updated successfully."
        )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = StudentSelector.get_academy_students(user=request.user)
        total = qs.count()
        active = qs.filter(status=StudentStatus.ACTIVE).count()
        inactive = qs.filter(status__in=[StudentStatus.INACTIVE, StudentStatus.SUSPENDED, StudentStatus.ARCHIVED]).count()
        enrolled = qs.filter(user__enrollments__status='ACTIVE').distinct().count()
        return api_response(data={
            "total_students": total,
            "active_students": active,
            "inactive_students": inactive,
            "enrolled_students": enrolled,
        })

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        student = self.get_object()
        StudentService.update_status(student, StudentStatus.ACTIVE)
        return api_response(message="Student activated.")

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        student = self.get_object()
        StudentService.update_status(student, StudentStatus.INACTIVE)
        return api_response(message="Student deactivated.")

    @action(detail=True, methods=['post'], url_path='send-email')
    def send_email(self, request, pk=None):
        student = self.get_object()
        subject = request.data.get('subject', '').strip()
        message = request.data.get('message', '').strip()

        if not subject:
            raise CubixSkillAPIException("Email subject is required.", code="SUBJECT_REQUIRED", status_code=400)
        if not message:
            raise CubixSkillAPIException("Email message is required.", code="MESSAGE_REQUIRED", status_code=400)

        recipient_email = student.user.email if student.user else None
        if not recipient_email:
            raise CubixSkillAPIException("Student does not have a valid email address.", code="NO_EMAIL", status_code=400)

        from emails.outbox_service import EmailJobService
        acad_id = request.user.academy_id if hasattr(request.user, 'academy_id') else (request.user.academy.id if hasattr(request.user, 'academy') and request.user.academy else None)
        context = {
            "user_name": student.display_name or (student.user.full_name if student.user else "Student"),
            "body": message,
            "academy_name": request.user.academy.name if (hasattr(request.user, 'academy') and request.user.academy) else "CubixSkill Academy"
        }

        job = EmailJobService.create_transactional_job(
            recipient_email=recipient_email,
            subject=subject,
            template_name="custom_notification",
            context=context,
            academy_uuid=acad_id,
            recipient_user_uuid=student.user.id if student.user else None,
            recipient_name=student.display_name or (student.user.full_name if student.user else "Student")
        )

        return api_response(
            data={"job_id": str(job.id), "status": "QUEUED"},
            message=f"Email queued successfully for {recipient_email}."
        )

    @action(detail=True, methods=['post'], url_path='resend-activation')
    def resend_activation(self, request, pk=None):
        student = self.get_object()
        StudentService.resend_activation_email(student, request.user.academy)
        return api_response(message="Activation email resent successfully.")

    @action(detail=False, methods=['post'], url_path='bulk-upload')
    def bulk_upload(self, request):
        course_id = request.data.get('course_id')
        rows = request.data.get('rows')

        if not course_id:
            raise CubixSkillAPIException("course_id is required.", code="COURSE_REQUIRED", status_code=400)
        if rows is None or not isinstance(rows, list):
            raise CubixSkillAPIException("rows must be a list of student records.", code="INVALID_ROWS", status_code=400)
        if len(rows) == 0:
            raise CubixSkillAPIException("rows list cannot be empty.", code="EMPTY_ROWS", status_code=400)

        try:
            result = StudentService.bulk_upload_students(
                academy=request.user.academy,
                course_id=str(course_id),
                rows=rows,
                created_by=request.user
            )

            return api_response(
                data=result,
                message="Bulk upload completed successfully.",
                status_code=status.HTTP_200_OK
            )
        except CubixSkillAPIException:
            raise
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error in bulk_upload endpoint: %s", str(e))
            raise CubixSkillAPIException("Bulk upload processing failed due to a server error.", code="BULK_UPLOAD_ERROR", status_code=500)

#--------------------------------------------------------------
# Student Self-Service ViewSet
#--------------------------------------------------------------

from rest_framework.parsers import JSONParser, FormParser, MultiPartParser

class StudentSelfServiceViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    @action(detail=False, methods=['get'])
    def profile(self, request):
        profile = getattr(request.user, 'student_profile', None)
        if not profile:
            raise CubixSkillAPIException("Student profile not found.", code="PROFILE_NOT_FOUND")
        return api_response(data=StudentProfileSerializer(profile).data)

    @action(detail=False, methods=['patch'])
    def update_profile(self, request):
        from django.db import transaction
        from storage.models import MediaFile, MediaType, MediaStatus

        profile = getattr(request.user, 'student_profile', None)
        if not profile:
            raise CubixSkillAPIException("Student profile not found.", code="PROFILE_NOT_FOUND")

        serializer = StudentSelfUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        with transaction.atomic():
            # 1. Update User attributes if provided
            user = request.user
            user_updated = False

            if 'full_name' in validated_data:
                new_full_name = validated_data.pop('full_name').strip()
                if new_full_name:
                    user.full_name = new_full_name
                    profile.display_name = new_full_name
                    user_updated = True

            if 'phone' in validated_data:
                new_phone = validated_data.pop('phone').strip()
                user.phone = new_phone
                user_updated = True

            if user_updated:
                user.save()

            # 2. Handle profile_photo_id if provided (can be None for removal)
            if 'profile_photo_id' in validated_data:
                photo_id = validated_data.pop('profile_photo_id')
                if photo_id is None:
                    profile.profile_photo = None
                else:
                    user_academy_id = user.academy_id if hasattr(user, 'academy_id') else (user.academy.id if hasattr(user, 'academy') and user.academy else None)
                    media = MediaFile.objects.filter(
                        id=photo_id,
                        uploaded_by_uuid=user.id,
                        status=MediaStatus.ACTIVE,
                        media_type=MediaType.IMAGE
                    ).first()

                    if not media or (user_academy_id and media.academy_uuid and media.academy_uuid != user_academy_id) or not (media.mime_type or '').startswith('image/'):
                        raise CubixSkillAPIException(
                            "The selected profile photo is invalid, not found, or belongs to another user/academy.",
                            code="INVALID_PROFILE_PHOTO",
                            status_code=400
                        )

                    profile.profile_photo = media

            # 3. Update remaining StudentProfile fields
            for attr, val in validated_data.items():
                setattr(profile, attr, val)

            profile.save()

        return api_response(data=StudentProfileSerializer(profile).data, message="Profile updated.")

#--------------------------------------------------------------
# Guardian ViewSet
#--------------------------------------------------------------

class StudentGuardianViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StudentGuardianSerializer

    def get_queryset(self):
        return StudentGuardian.objects.filter(student__user__academy=self.request.user.academy)

#--------------------------------------------------------------
# Document ViewSet
#--------------------------------------------------------------

class StudentDocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StudentDocumentSerializer

    def get_queryset(self):
        return StudentDocument.objects.filter(student__user__academy=self.request.user.academy)

#--------------------------------------------------------------
# Note ViewSet
#--------------------------------------------------------------

class StudentNoteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StudentNoteSerializer

    def get_queryset(self):
        return StudentNote.objects.filter(student__user__academy=self.request.user.academy)

#--------------------------------------------------------------
# Tag ViewSet
#--------------------------------------------------------------

class StudentTagViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StudentTagSerializer

    def get_queryset(self):
        return StudentTag.objects.filter(academy=self.request.user.academy)

#--------------------------------------------------------------
# Student Custom Field ViewSet
#--------------------------------------------------------------

from students.models import StudentCustomFieldDefinition
from students.serializers import StudentCustomFieldDefinitionSerializer

class StudentCustomFieldViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StudentCustomFieldDefinitionSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'academy') and user.academy:
            return StudentCustomFieldDefinition.objects.filter(academy=user.academy)
        return StudentCustomFieldDefinition.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User is not associated with an Academy.")
        key = serializer.validated_data.get('key', '').lower().replace(' ', '_')
        if not key:
            key = serializer.validated_data.get('label', '').lower().replace(' ', '_')
        serializer.save(academy=academy, key=key)

