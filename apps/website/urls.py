from django.urls import path
from website.views import (
    PublicWebsiteConfigView,
    PublicAcademyCoursesView,
    PublicAcademyCourseDetailView,
    StudentPortalBrandingView,
    AcademyWebsiteSettingsView,
    AcademyThemeColorUpdateView,
)

# --------------------------------------------------------------
# Website URL Router Configuration
# Centralized REST endpoints for public website config, student branding,
# and Academy website text/theme color settings.
# --------------------------------------------------------------

urlpatterns = [
    path('public/academies/<slug:academy_slug>/website/', PublicWebsiteConfigView.as_view(), name='public-website-config'),
    path('public/academies/<slug:academy_slug>/courses/', PublicAcademyCoursesView.as_view(), name='public-academy-courses'),
    path('public/academies/<slug:academy_slug>/courses/<slug:course_slug>/', PublicAcademyCourseDetailView.as_view(), name='public-academy-course-detail'),
    path('student/branding/', StudentPortalBrandingView.as_view(), name='student-branding'),
    path('academy/website-settings/', AcademyWebsiteSettingsView.as_view(), name='academy-website-settings'),
    path('academy/settings/', AcademyThemeColorUpdateView.as_view(), name='academy-theme-color-settings'),
]
