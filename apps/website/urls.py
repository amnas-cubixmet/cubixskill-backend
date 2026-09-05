from django.urls import path
from website.views import (
    PublicWebsiteConfigView,
    PublicAcademyCoursesView,
    PublicAcademyCourseDetailView,
    PublicLessonPreviewView,
    StudentPortalBrandingView,
    AcademyWebsiteSettingsView,
    AcademyWebsitePublishView,
    AcademyThemeColorUpdateView,
)

# --------------------------------------------------------------
# Website URL Router Configuration
# Centralized REST endpoints for public website config, student branding,
# and Academy website single-theme draft/publish settings.
# --------------------------------------------------------------

urlpatterns = [
    path('public/academies/<slug:academy_slug>/website/', PublicWebsiteConfigView.as_view(), name='public-website-config'),
    path('public/academies/<slug:academy_slug>/courses/', PublicAcademyCoursesView.as_view(), name='public-academy-courses'),
    path('public/academies/<slug:academy_slug>/courses/<slug:course_slug>/', PublicAcademyCourseDetailView.as_view(), name='public-academy-course-detail'),
    path('public/academies/<slug:academy_slug>/courses/<slug:course_slug>/lessons/<uuid:lesson_id>/preview/', PublicLessonPreviewView.as_view(), name='public-lesson-preview'),
    path('student/branding/', StudentPortalBrandingView.as_view(), name='student-branding'),
    path('settings/', AcademyWebsiteSettingsView.as_view(), name='academy-website-settings'),
    path('settings/publish/', AcademyWebsitePublishView.as_view(), name='academy-website-publish'),
    path('academy/website-settings/', AcademyWebsiteSettingsView.as_view(), name='academy-website-settings-alias'),
    path('academy/website-settings/publish/', AcademyWebsitePublishView.as_view(), name='academy-website-publish-alias'),
    path('academy/settings/', AcademyThemeColorUpdateView.as_view(), name='academy-theme-color-settings'),
]
