from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from users_roles.models import User
from courses.models import Course
from core.utils import CubixSkillAPIException
from enrollments.models import Enrollment, AccessType, EnrollmentSource
from enrollments.selectors import EnrollmentSelector
from enrollments.services import EnrollmentService
from enrollments.permissions import IsStudentOwnerOrAcademyStaff
from enrollments.serializers import (
    EnrollmentSerializer,
    EnrollmentDetailSerializer,
    CreateEnrollmentSerializer,
    BulkEnrollmentSerializer,
    ExtendEnrollmentSerializer,
    LifecycleActionSerializer,
    EnrollmentAccessPeriodSerializer,
    EnrollmentEventSerializer,
)

#--------------------------------------------------------------
# Student Enrollment ViewSet
#--------------------------------------------------------------

class StudentEnrollmentViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Students to view their own course enrollments."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EnrollmentSerializer

    def get_queryset(self):
        return EnrollmentSelector.get_student_enrollments(self.request.user)

#--------------------------------------------------------------
# Enrollment ViewSet
#--------------------------------------------------------------

class EnrollmentViewSet(viewsets.ModelViewSet):
    """ViewSet for Academy Admins/Staff to manage student enrollments."""
    permission_classes = [permissions.IsAuthenticated, IsStudentOwnerOrAcademyStaff]

    def get_serializer_class(self):
        if self.action in ['retrieve']:
            return EnrollmentDetailSerializer
        return EnrollmentSerializer

    def get_queryset(self):
        params = self.request.query_params
        return EnrollmentSelector.get_academy_enrollments(
            user=self.request.user,
            course_id=params.get('course'),
            status=params.get('status'),
            access_type=params.get('access_type'),
            source=params.get('source'),
            expired=params.get('expired') == 'true' if params.get('expired') else None,
            expiring_soon=params.get('expiring_soon') == 'true' if params.get('expiring_soon') else None,
            search=params.get('search')
        )

    def create(self, request, *args, **kwargs):
        serializer = CreateEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            student = User.objects.get(id=data['student_id'])
            course = Course.objects.get(id=data['course_id'])
        except User.DoesNotExist:
            raise CubixSkillAPIException("Student user not found.", code="USER_NOT_FOUND", status_code=404)
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

        enrollment = EnrollmentService.enroll_student(
            student=student,
            course=course,
            access_type=data.get('access_type', AccessType.FULL),
            source=data.get('source', EnrollmentSource.MANUAL),
            source_reference=data.get('source_reference', ''),
            is_lifetime=data.get('is_lifetime', True),
            access_expires_at=data.get('access_expires_at'),
            created_by=request.user
        )
        return Response(EnrollmentDetailSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.resume_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def extend(self, request, pk=None):
        enrollment = self.get_object()
        serializer = ExtendEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = EnrollmentService.extend_access(
            enrollment,
            additional_days=data.get('additional_days'),
            new_expiry_date=data.get('new_expiry_date'),
            reason=data.get('reason', ''),
            performed_by=request.user
        )
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.suspend_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.resume_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.revoke_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        enrollment = self.get_object()
        serializer = LifecycleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = EnrollmentService.cancel_enrollment(enrollment, reason=serializer.validated_data.get('reason', ''), performed_by=request.user)
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        enrollment = self.get_object()
        is_lifetime = request.data.get('is_lifetime', True)
        access_expires_at = request.data.get('access_expires_at')
        source_reference = request.data.get('source_reference', '')

        updated = EnrollmentService.upgrade_demo_to_full(
            enrollment,
            is_lifetime=is_lifetime,
            access_expires_at=access_expires_at,
            source_reference=source_reference,
            performed_by=request.user
        )
        return Response(EnrollmentDetailSerializer(updated).data)

    @action(detail=False, methods=['post'])
    def bulk(self, request):
        serializer = BulkEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            course = Course.objects.get(id=data['course_id'])
        except Course.DoesNotExist:
            raise CubixSkillAPIException("Course not found.", code="COURSE_NOT_FOUND", status_code=404)

        students = User.objects.filter(id__in=data['student_ids'])
        results = EnrollmentService.bulk_enroll(
            students=students,
            course=course,
            access_type=data.get('access_type', AccessType.FULL),
            is_lifetime=data.get('is_lifetime', True),
            access_expires_at=data.get('access_expires_at'),
            created_by=request.user
        )
        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        enrollment = self.get_object()
        history = EnrollmentSelector.get_enrollment_history(enrollment.id)
        return Response({
            'access_periods': EnrollmentAccessPeriodSerializer(history['periods'], many=True).data,
            'events': EnrollmentEventSerializer(history['events'], many=True).data
        })
