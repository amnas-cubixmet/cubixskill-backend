import re
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from website.models import WebsiteSettings

# --------------------------------------------------------------
# Central Website Service
# Manages public website configuration, text updates, student portal
# branding payload assembly, and cache invalidation.
# --------------------------------------------------------------

HEX_COLOR_REGEX = re.compile(r'^#(?:[0-9a-fA-F]{3}){1,2}$')

class WebsiteService:

    @classmethod
    def validate_hex_color(cls, color_code: str) -> str:
        """
        Validates hex theme color format e.g. #2563EB or #09F.
        Prevents raw CSS or script injections.
        """
        if not color_code or not HEX_COLOR_REGEX.match(color_code):
            raise ValidationError({"theme_color": "Invalid theme color format. Must be hex code e.g. #2563EB."})
        return color_code.upper()

    @classmethod
    def get_or_create_settings(cls, academy: Academy) -> WebsiteSettings:
        """
        Retrieves existing WebsiteSettings or creates initial defaults for an Academy.
        """
        settings, _ = WebsiteSettings.objects.get_or_create(academy=academy)
        return settings

    @classmethod
    def update_website_settings(cls, academy: Academy, data: dict, updated_by=None) -> WebsiteSettings:
        """
        Updates predefined website text fields with strict backend character limit validation.
        Invalidates cached public website configuration on save.
        """
        settings = cls.get_or_create_settings(academy)

        home_hero_title = data.get('home_hero_title', settings.home_hero_title)
        home_hero_subtitle = data.get('home_hero_subtitle', settings.home_hero_subtitle)
        courses_title = data.get('courses_title', settings.courses_title)
        courses_description = data.get('courses_description', settings.courses_description)
        contact_title = data.get('contact_title', settings.contact_title)
        contact_description = data.get('contact_description', settings.contact_description)

        if len(home_hero_title) > 100:
            raise ValidationError({"home_hero_title": "Hero title must not exceed 100 characters."})
        if len(home_hero_subtitle) > 250:
            raise ValidationError({"home_hero_subtitle": "Hero subtitle must not exceed 250 characters."})
        if len(courses_title) > 100:
            raise ValidationError({"courses_title": "Courses title must not exceed 100 characters."})
        if len(courses_description) > 500:
            raise ValidationError({"courses_description": "Courses description must not exceed 500 characters."})
        if len(contact_title) > 100:
            raise ValidationError({"contact_title": "Contact title must not exceed 100 characters."})
        if len(contact_description) > 500:
            raise ValidationError({"contact_description": "Contact description must not exceed 500 characters."})

        settings.home_hero_title = home_hero_title
        settings.home_hero_subtitle = home_hero_subtitle
        settings.courses_title = courses_title
        settings.courses_description = courses_description
        settings.contact_title = contact_title
        settings.contact_description = contact_description
        settings.updated_by = updated_by
        settings.save()

        # Invalidate public cache
        cache_key = f"academy:{academy.id}:website_config"
        cache.delete(cache_key)

        return settings

    @classmethod
    def get_public_website_config(cls, academy: Academy) -> dict:
        """
        Builds public website configuration JSON combining Academy branding and WebsiteSettings text.
        Caches payload for fast public reads.
        """
        cache_key = f"academy:{academy.id}:website_config"
        cached_config = cache.get(cache_key)
        if cached_config:
            return cached_config

        settings = cls.get_or_create_settings(academy)

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        config = {
            "academy": {
                "name": academy.name,
                "slug": academy.slug,
                "logo": logo_url,
                "favicon": favicon_url,
                "theme_color": getattr(academy, 'theme_color', '#2563EB') or '#2563EB',
                "email": getattr(academy, 'email', '') or '',
                "phone": getattr(academy, 'phone', '') or ''
            },
            "home": {
                "hero_title": settings.home_hero_title,
                "hero_subtitle": settings.home_hero_subtitle
            },
            "courses": {
                "title": settings.courses_title,
                "description": settings.courses_description
            },
            "contact": {
                "title": settings.contact_title,
                "description": settings.contact_description
            }
        }

        cache.set(cache_key, config, timeout=3600)
        return config

    @classmethod
    def get_student_branding(cls, user) -> dict:
        """
        Assembles student portal branding response (name, logo, favicon, theme_color).
        """
        academy = getattr(user, 'academy', None)
        if not academy and hasattr(user, 'student_profile') and getattr(user.student_profile, 'academy', None):
            academy = user.student_profile.academy

        if not academy:
            return {
                "academy_name": "CubixSkill Academy",
                "logo": "",
                "favicon": "",
                "theme_color": "#2563EB"
            }

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        return {
            "academy_name": academy.name,
            "logo": logo_url,
            "favicon": favicon_url,
            "theme_color": getattr(academy, 'theme_color', '#2563EB') or '#2563EB'
        }
