from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from storage.models import MediaFile
from leads.models import Lead, LeadFollowUp, LeadCourseInterest, LeadNote, LeadImportJob
from leads.selectors import LeadSelector
from leads.services import (
    LeadService,
    LeadAssignmentService,
    LeadFollowUpService,
    LeadStatusService,
    LeadConversionService,
    LeadNoteService,
)
from leads.serializers import (
    LeadSerializer,
    PublicLeadEnquirySerializer,
    AssignLeadSerializer,
    TransitionStatusSerializer,
    ConvertLeadSerializer,
    ScheduleFollowUpSerializer,
    CompleteFollowUpSerializer,
    CreateLeadNoteSerializer,
    AddCourseInterestSerializer,
    LeadFollowUpSerializer,
    LeadNoteSerializer,
    LeadCourseInterestSerializer,
    LeadImportJobSerializer,
)
from leads.tasks import process_lead_import_job

# --------------------------------------------------------------
# 1. Public Lead Enquiry Endpoint
# Public enquiry endpoint for visitors/prospects.
# Accepts enquiry submission without exposing CRM records or internal history.
# --------------------------------------------------------------

class PublicLeadEnquiryView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, academy_slug):
        academy = get_object_or_404(Academy, slug=academy_slug)

        serializer = PublicLeadEnquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course = None
        course_id = data.get('course_id')
        if course_id:
            course = get_object_or_404(Course, id=course_id)
            if course.academy != academy:
                raise ValidationError({"course_id": "Course does not belong to the specified Academy."})

        metadata = {}
        if data.get('message'):
            metadata['message'] = data['message']
        if data.get('utm_source'):
            metadata['utm_source'] = data['utm_source']
        if data.get('utm_medium'):
            metadata['utm_medium'] = data['utm_medium']
        if data.get('utm_campaign'):
            metadata['utm_campaign'] = data['utm_campaign']

        lead, created = LeadService.create_or_update_lead(
            academy=academy,
            full_name=data['full_name'],
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            source='COURSE_ENQUIRY' if course else 'WEBSITE',
            course=course,
            metadata=metadata
        )

        return Response({
            "message": "Thank you for your enquiry. Our team will contact you shortly.",
            "success": True
        }, status=status.HTTP_201_CREATED)

# --------------------------------------------------------------
# 2. Staff Lead ViewSet
# Provides CRM management for authorized Academy Admin/Staff users.
# --------------------------------------------------------------

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Academy is derived from the authenticated user so clients cannot access Leads belonging to another tenant.
        academy = getattr(user, 'academy', None)
        if not academy and not getattr(user, 'is_staff', False):
            return Lead.objects.none()

        return LeadSelector.get_academy_leads(
            academy=academy,
            status=self.request.query_params.get('status'),
            priority=self.request.query_params.get('priority'),
            source=self.request.query_params.get('source'),
            assigned_to_id=self.request.query_params.get('assigned_to'),
            course_id=self.request.query_params.get('course_id'),
            search=self.request.query_params.get('search'),
            follow_up_due_today=self.request.query_params.get('follow_up_due_today') == 'true'
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if request.query_params.get('include_metrics') == 'true':
            academy = getattr(request.user, 'academy', None)
            metrics = LeadSelector.get_dashboard_metrics(academy)
            if isinstance(response.data, dict):
                response.data['metrics'] = metrics
        return response

    def create(self, request, *args, **kwargs):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to create Leads.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lead, _ = LeadService.create_or_update_lead(
            academy=academy,
            full_name=data['full_name'],
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            source=data.get('source', 'MANUAL'),
            source_detail=data.get('source_detail', ''),
            priority=data.get('priority', 'NORMAL'),
            preferred_contact_method=data.get('preferred_contact_method', 'EMAIL'),
            metadata=data.get('metadata', {}),
            created_by=request.user
        )

        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def status(self, request, pk=None):
        lead = self.get_object()
        serializer = TransitionStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_lead = LeadStatusService.transition_status(
            lead=lead,
            new_status=serializer.validated_data['status'],
            performed_by=request.user,
            lost_reason=serializer.validated_data.get('lost_reason', '')
        )
        return Response(LeadSerializer(updated_lead).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        lead = self.get_object()
        serializer = AssignLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user = get_object_or_404(User, id=serializer.validated_data['assigned_to_id'])
        LeadAssignmentService.assign_lead(
            lead=lead,
            assigned_to_user=target_user,
            assigned_by_user=request.user,
            reason=serializer.validated_data.get('reason', '')
        )
        lead.refresh_from_db()
        return Response(LeadSerializer(lead).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        lead = self.get_object()
        serializer = ConvertLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course = None
        course_id = serializer.validated_data.get('course_id')
        if course_id:
            course = get_object_or_404(Course, id=course_id)

        user, student, enrollment = LeadConversionService.convert_to_student(
            lead=lead,
            course=course,
            converted_by=request.user,
            create_enrollment=serializer.validated_data.get('create_enrollment', True),
            enrollment_access_type=serializer.validated_data.get('enrollment_access_type', 'FULL')
        )

        return Response({
            "message": "Lead converted successfully.",
            "user_id": str(user.id),
            "student_id": str(student.id),
            "enrollment_id": str(enrollment.id) if enrollment else None,
            "lead": LeadSerializer(lead).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        lead = self.get_object()
        timeline = LeadSelector.get_lead_timeline(lead)
        return Response(timeline, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], url_path='notes')
    def notes(self, request, pk=None):
        lead = self.get_object()
        if request.method == 'GET':
            notes = lead.notes.all()
            return Response(LeadNoteSerializer(notes, many=True).data)

        serializer = CreateLeadNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        note = LeadNoteService.add_note(
            lead=lead,
            author=request.user,
            content=serializer.validated_data['content'],
            is_pinned=serializer.validated_data.get('is_pinned', False)
        )
        return Response(LeadNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='follow-ups')
    def follow_ups(self, request, pk=None):
        lead = self.get_object()
        if request.method == 'GET':
            follow_ups = lead.follow_ups.all()
            return Response(LeadFollowUpSerializer(follow_ups, many=True).data)

        serializer = ScheduleFollowUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        assigned_to = None
        assigned_to_id = serializer.validated_data.get('assigned_to_id')
        if assigned_to_id:
            assigned_to = get_object_or_404(User, id=assigned_to_id)

        follow_up = LeadFollowUpService.schedule_follow_up(
            lead=lead,
            scheduled_at=serializer.validated_data['scheduled_at'],
            follow_up_type=serializer.validated_data.get('follow_up_type', 'CALL'),
            assigned_to=assigned_to,
            created_by=request.user,
            notes=serializer.validated_data.get('notes', '')
        )
        return Response(LeadFollowUpSerializer(follow_up).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='course-interests')
    def course_interests(self, request, pk=None):
        lead = self.get_object()
        if request.method == 'GET':
            interests = lead.course_interests.all()
            return Response(LeadCourseInterestSerializer(interests, many=True).data)

        serializer = AddCourseInterestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course = get_object_or_404(Course, id=serializer.validated_data['course_id'])
        if course.academy != lead.academy:
            raise ValidationError("Course does not belong to the Lead's Academy.")

        interest, _ = LeadCourseInterest.objects.get_or_create(
            lead=lead,
            course=course,
            defaults={'interest_level': serializer.validated_data.get('interest_level', 'HIGH')}
        )

        return Response(LeadCourseInterestSerializer(interest).data, status=status.HTTP_201_CREATED)

#--------------------------------------------------------------
# 3. Follow-Up Completion ViewSet
#--------------------------------------------------------------

class LeadFollowUpViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        follow_up = get_object_or_404(LeadFollowUp, id=pk)
        if follow_up.lead.academy != request.user.academy:
            raise PermissionDenied("Access denied.")

        serializer = CompleteFollowUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        completed_fu = LeadFollowUpService.complete_follow_up(
            follow_up=follow_up,
            outcome=serializer.validated_data.get('outcome', ''),
            notes=serializer.validated_data.get('notes', ''),
            completed_by=request.user
        )

        return Response(LeadFollowUpSerializer(completed_fu).data, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# 4. Lead Import ViewSet
#--------------------------------------------------------------

class LeadImportViewSet(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to import leads.")

        media_file_id = request.data.get('media_file_id')
        if not media_file_id:
            raise ValidationError({"media_file_id": "media_file_id is required."})

        media_file = get_object_or_404(MediaFile, id=media_file_id)

        job = LeadImportJob.objects.create(
            academy=academy,
            uploaded_by=request.user,
            source_media_file=media_file
        )

        process_lead_import_job.delay(str(job.id))

        return Response(LeadImportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
