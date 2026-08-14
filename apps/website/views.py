from django.shortcuts import get_object_or_404
from django.core.cache import cache
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from courses.serializers import CourseListSerializer, CourseDetailSerializer
from website.selectors import WebsiteSelector
from website.services import WebsiteService
from website.serializers import (
    WebsiteSettingsSerializer,
    UpdateWebsiteSettingsSerializer,
    UpdateThemeColorSerializer,
)

# --------------------------------------------------------------
# 1. Public Academy Website Endpoints
# Read-only configuration and course endpoints for public visitors.
# --------------------------------------------------------------

class PublicWebsiteConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug):
        academy = get_object_or_404(Academy, slug=academy_slug, is_active=True)
        config = WebsiteService.get_public_website_config(academy)
        return Response(config, status=status.HTTP_200_OK)

class PublicAcademyCoursesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug):
        academy = get_object_or_404(Academy, slug=academy_slug, is_active=True)
        courses = WebsiteSelector.get_public_academy_courses(academy)
        serializer = CourseListSerializer(courses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicAcademyCourseDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug, course_slug):
        academy = get_object_or_404(Academy, slug=academy_slug, is_active=True)
        course = WebsiteSelector.get_public_academy_course_by_slug(academy, course_slug)
        serializer = CourseDetailSerializer(course)
        return Response(serializer.data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Student Portal Branding Endpoint
# Returns branding token payload (name, logo, favicon, theme_color)
# for the authenticated student context.
# --------------------------------------------------------------

class StudentPortalBrandingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        branding = WebsiteService.get_student_branding(request.user)
        return Response(branding, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 3. Staff Website Settings API
# Enables Academy Admin / Staff to edit predefined public text settings.
# --------------------------------------------------------------

class AcademyWebsiteSettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_academy(self, user):
        academy = getattr(user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to manage website settings.")
        return academy

    def get(self, request):
        academy = self.get_academy(request.user)
        settings = WebsiteService.get_or_create_settings(academy)
        serializer = WebsiteSettingsSerializer(settings)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        academy = self.get_academy(request.user)
        serializer = UpdateWebsiteSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        settings = WebsiteService.update_website_settings(
            academy=academy,
            data=serializer.validated_data,
            updated_by=request.user
        )

        return Response(WebsiteSettingsSerializer(settings).data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 4. Academy Theme Color Settings API
# Updates single Academy.theme_color field with hex format validation.
# --------------------------------------------------------------

class AcademyThemeColorUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to update theme color.")

        serializer = UpdateThemeColorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        theme_color = serializer.validated_data['theme_color']
        academy.theme_color = theme_color
        academy.save(update_fields=['theme_color'])

        # Invalidate public cache
        cache_key = f"academy:{academy.id}:website_config"
        cache.delete(cache_key)

        return Response({
            "message": "Theme color updated successfully.",
            "theme_color": theme_color
        }, status=status.HTTP_200_OK)
