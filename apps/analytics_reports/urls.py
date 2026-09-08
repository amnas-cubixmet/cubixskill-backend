from analytics_reports.views import (
    AcademyDashboardAnalyticsView,
    CourseAnalyticsView,
    LeadAnalyticsView,
    LiveClassAnalyticsView,
    PlatformDashboardAnalyticsView,
    ReportJobViewSet,
    RevenueAnalyticsView,
    SavedReportViewSet,
)
from django.urls import include, path
from rest_framework.routers import DefaultRouter

# --------------------------------------------------------------
# Analytics & Reports URL Router Configuration
# REST API endpoints for Academy & Platform analytics dashboards,
# domain-specific metrics, SavedReport management, and ReportJob generation.
# ReportJob tracks export generation and status for asynchronous tasks.
# Academy analytics enforce tenant isolation; Platform reports use academy = null.
# --------------------------------------------------------------


router = DefaultRouter()
router.register(r'reports/saved', SavedReportViewSet, basename='saved-report')
router.register(r'reports', ReportJobViewSet, basename='report-job')

urlpatterns = [
    path('analytics/dashboard/', AcademyDashboardAnalyticsView.as_view(), name='analytics-dashboard'),
    path('admin/analytics/dashboard/', PlatformDashboardAnalyticsView.as_view(), name='admin-analytics-dashboard'),
    path('analytics/courses/', CourseAnalyticsView.as_view(), name='analytics-courses'),
    path('analytics/courses/<str:course_id>/', CourseAnalyticsView.as_view(), name='analytics-course-detail'),
    path('analytics/revenue/', RevenueAnalyticsView.as_view(), name='analytics-revenue'),
    path('analytics/leads/', LeadAnalyticsView.as_view(), name='analytics-leads'),
    path('analytics/live-classes/', LiveClassAnalyticsView.as_view(), name='analytics-live-classes'),
    path('', include(router.urls)),
]
