from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from students.models import  StudentGuardian, StudentDocument, StudentNote, StudentTag, StudentStatus
from students.selectors import StudentSelector
from students.services import StudentService
from students.serializers import (
    StudentProfileSerializer, StudentCreateSerializer, StudentSelfUpdateSerializer,
    StudentGuardianSerializer, StudentDocumentSerializer, StudentNoteSerializer, StudentTagSerializer
)
from core.permissions import CanAccessAcademyPermission
from core.utils import CubixSkillAPIException, api_response

#--------------------------------------------------------------
# Student Admin ViewSet
#--------------------------------------------------------------

class StudentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]
    serializer_class = StudentProfileSerializer

    def get_queryset(self):
        search_query = self.request.query_params.get('search')
        status_filter = self.request.query_params.get('status')
        return StudentSelector.get_academy_students(
            user=self.request.user,
            search_query=search_query,
            status_filter=status_filter
        )

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

        return api_response(
            data=StudentProfileSerializer(student).data,
            message="Student profile created successfully.",
            status_code=status.HTTP_201_CREATED
        )

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

        from emails.services import send_transactional_email
        context = {
            "user_name": student.display_name or student.user.full_name or "Student",
            "body": message,
            "academy_name": request.user.academy.name if (hasattr(request.user, 'academy') and request.user.academy) else "CubixSkill Academy"
        }

        success = send_transactional_email(
            recipient=recipient_email,
            template_name="custom_notification",
            subject=subject,
            context=context
        )

        if not success:
            raise CubixSkillAPIException("Failed to deliver email via SMTP backend.", code="EMAIL_DELIVERY_FAILED", status_code=500)

        return api_response(message=f"Email sent successfully to {recipient_email}.")

#--------------------------------------------------------------
# Student Self-Service ViewSet
#--------------------------------------------------------------

class StudentSelfServiceViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def profile(self, request):
        profile = getattr(request.user, 'student_profile', None)
        if not profile:
            raise CubixSkillAPIException("Student profile not found.", code="PROFILE_NOT_FOUND")
        return api_response(data=StudentProfileSerializer(profile).data)

    @action(detail=False, methods=['patch'])
    def update_profile(self, request):
        profile = getattr(request.user, 'student_profile', None)
        if not profile:
            raise CubixSkillAPIException("Student profile not found.", code="PROFILE_NOT_FOUND")

        serializer = StudentSelfUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
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
