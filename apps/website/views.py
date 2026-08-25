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

import uuid

def get_academy_by_identifier(identifier):
    try:
        val = uuid.UUID(str(identifier))
        return get_object_or_404(Academy, id=val, is_active=True)
    except (ValueError, TypeError):
        return get_object_or_404(Academy, slug=identifier, is_active=True)

# --------------------------------------------------------------
# 1. Public Academy Website Endpoints
# Read-only configuration and course endpoints for public visitors.
# --------------------------------------------------------------

class PublicWebsiteConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug):
        academy = get_academy_by_identifier(academy_slug)
        config = WebsiteService.get_public_website_config(academy)
        return Response(config, status=status.HTTP_200_OK)

class PublicAcademyCoursesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug):
        academy = get_academy_by_identifier(academy_slug)
        courses = WebsiteSelector.get_public_academy_courses(academy)
        serializer = CourseListSerializer(courses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicAcademyCourseDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, academy_slug, course_slug):
        academy = get_academy_by_identifier(academy_slug)
        course = WebsiteSelector.get_public_academy_course_by_slug(academy, course_slug)
        serializer = CourseDetailSerializer(course)
        return Response(serializer.data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Student Portal Branding Endpoint
# Returns branding token payload (name, logo, favicon, theme_color)
# --------------------------------------------------------------

class StudentPortalBrandingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        branding = WebsiteService.get_student_branding(request.user)
        return Response(branding, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 3. Staff Website & Single Theme Builder API
# Enables Academy Admin / Staff to manage draft and publish theme configs.
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

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        has_unpublished_changes = settings.draft_config != settings.published_config

        return Response({
            "academy_id": str(academy.id),
            "academy_name": academy.name,
            "academy_slug": academy.slug,
            "logo_url": logo_url,
            "favicon_url": favicon_url,
            "draft_config": settings.draft_config,
            "published_config": settings.published_config,
            "published_at": settings.published_at.isoformat() if settings.published_at else None,
            "has_unpublished_changes": has_unpublished_changes,
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        academy = self.get_academy(request.user)
        data = request.data or {}

        settings = WebsiteService.update_draft_config(
            academy=academy,
            data=data,
            updated_by=request.user
        )

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        has_unpublished_changes = settings.draft_config != settings.published_config

        return Response({
            "message": "Draft website settings saved successfully.",
            "draft_config": settings.draft_config,
            "published_config": settings.published_config,
            "published_at": settings.published_at.isoformat() if settings.published_at else None,
            "has_unpublished_changes": has_unpublished_changes,
            "logo_url": logo_url,
            "favicon_url": favicon_url,
        }, status=status.HTTP_200_OK)

class AcademyWebsitePublishView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to publish website settings.")

        settings = WebsiteService.publish_theme(academy=academy, updated_by=request.user)

        return Response({
            "message": "Website theme successfully published to production!",
            "published_config": settings.published_config,
            "published_at": settings.published_at.isoformat() if settings.published_at else None,
            "has_unpublished_changes": False,
        }, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 4. Academy Theme Color Update Legacy Endpoint
# --------------------------------------------------------------

class AcademyThemeColorUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy:
            raise ValidationError("User must belong to an Academy to update theme color.")

        color = request.data.get('theme_color')
        if not color:
            raise ValidationError({"theme_color": "Theme color is required."})

        validated_color = WebsiteService.validate_hex_color(color, "theme_color")
        settings = WebsiteService.get_or_create_settings(academy)
        current_draft = dict(settings.draft_config or {})
        current_draft["primary_color"] = validated_color
        settings.draft_config = current_draft
        settings.save(update_fields=['draft_config'])

        WebsiteService.publish_theme(academy, updated_by=request.user)

        return Response({
            "message": "Theme color updated and published successfully.",
            "theme_color": validated_color
        }, status=status.HTTP_200_OK)
