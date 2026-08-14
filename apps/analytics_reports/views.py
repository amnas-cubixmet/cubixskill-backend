from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

from analytics_reports.models import ReportJob, SavedReport, ReportStatus
from analytics_reports.selectors import AnalyticsSelector
from analytics_reports.services import ReportService
from analytics_reports.serializers import (
    ReportJobSerializer,
    CreateReportJobRequestSerializer,
    SavedReportSerializer,
)

# --------------------------------------------------------------
# 1. Academy & Platform Dashboard Analytics Views
# Current analytics may use live database queries for real-time metrics.
# Analytics aggregates domain data but is not the source of truth;
# Payment, Progress, Leads, and Credits domains remain authoritative for data.
# Academy analytics must enforce tenant isolation.
# Platform reports use academy = null where supported for Super Admin.
# --------------------------------------------------------------


class AcademyDashboardAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access analytics dashboard.")

        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        dashboard_data = AnalyticsSelector.get_academy_dashboard(
            academy=academy,
            date_from=date_from,
            date_to=date_to
        )
        return Response(dashboard_data, status=status.HTTP_200_OK)


class PlatformDashboardAnalyticsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        platform_data = AnalyticsSelector.get_platform_dashboard(
            date_from=date_from,
            date_to=date_to
        )
        return Response(platform_data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Specialized Domain Analytics Views
# Exposes course performance, revenue, lead pipeline, and live class metrics.
# Payment, Progress, Leads, and Credits domains remain authoritative for data.
# Academy analytics must enforce tenant isolation.
# --------------------------------------------------------------

class CourseAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, course_id=None):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access course analytics.")

        results = AnalyticsSelector.get_course_analytics(academy=academy, course_id=course_id)
        if course_id and results:
            return Response(results[0], status=status.HTTP_200_OK)
        return Response(results, status=status.HTTP_200_OK)


class RevenueAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access revenue analytics.")

        revenue_data = AnalyticsSelector.get_revenue_analytics(academy=academy)
        return Response(revenue_data, status=status.HTTP_200_OK)


class LeadAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access lead analytics.")

        lead_data = AnalyticsSelector.get_lead_analytics(academy=academy)
        return Response(lead_data, status=status.HTTP_200_OK)


class LiveClassAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access live class analytics.")

        live_data = AnalyticsSelector.get_live_class_analytics(academy=academy)
        return Response(live_data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 3. Report Job Lifecycle ViewSet & Secure Download
# ReportJob tracks export generation and status for asynchronous tasks.
# Large CSV/XLSX exports run asynchronously through Celery workers.
# Academy analytics must enforce tenant isolation.
# --------------------------------------------------------------

class ReportJobViewSet(viewsets.ModelViewSet):
    serializer_class = ReportJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy and not getattr(self.request.user, 'is_staff', False):
            return ReportJob.objects.none()

        if getattr(self.request.user, 'is_staff', False):
            return ReportJob.objects.all()

        return ReportJob.objects.filter(academy=academy)

    def create(self, request, *args, **kwargs):
        serializer = CreateReportJobRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job = ReportService.create_report_job(
            user=request.user,
            report_type=serializer.validated_data['report_type'],
            format_type=serializer.validated_data.get('format', 'CSV'),
            filters=serializer.validated_data.get('filters', {})
        )

        return Response(ReportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        job = self.get_object()

        if job.status != ReportStatus.COMPLETED or not job.result_media:
            raise ValidationError("Report generation is not completed or has expired.")

        media_file = job.result_media
        try:
            file_obj = media_file.file
            response = HttpResponse(file_obj.read(), content_type=media_file.mime_type or 'text/csv')
            response['Content-Disposition'] = f'attachment; filename="{job.result_filename or media_file.original_filename}"'
            return response
        except Exception as exc:
            raise Http404(f"Report file could not be read: {exc}")

# --------------------------------------------------------------
# 4. Saved Reports Management ViewSet
# SavedReport stores reusable report configuration for Academy staff.
# --------------------------------------------------------------


class SavedReportViewSet(viewsets.ModelViewSet):
    serializer_class = SavedReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy:
            return SavedReport.objects.none()
        return SavedReport.objects.filter(academy=academy)

    def perform_create(self, serializer):
        academy = getattr(self.request.user, 'academy', None)
        serializer.save(academy=academy, created_by=self.request.user)
