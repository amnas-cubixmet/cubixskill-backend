import re

from academy.models import Academy
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from website.models import WebsiteSettings, default_theme_config

# --------------------------------------------------------------
# Central Website Service
# Manages single Academy Theme & Website Settings configuration.
# Handles draft edits, publish operations, and cache management.
# --------------------------------------------------------------

HEX_COLOR_REGEX = re.compile(r'^#(?:[0-9a-fA-F]{3}){1,2}$')

class WebsiteService:

    @classmethod
    def validate_hex_color(cls, color_code: str, field_name: str = "color") -> str:
        """
        Validates hex theme color format e.g. #2563EB or #09F.
        Prevents raw CSS or script injections.
        """
        if not color_code or not HEX_COLOR_REGEX.match(color_code):
            raise ValidationError({field_name: "Invalid theme color format. Must be hex code e.g. #2563EB."})
        return color_code.upper()

    @classmethod
    def get_or_create_settings(cls, academy: Academy) -> WebsiteSettings:
        """
        Retrieves existing WebsiteSettings or creates initial defaults for an Academy.
        Ensures draft_config and published_config contain valid merged defaults.
        """
        settings, created = WebsiteSettings.objects.get_or_create(academy=academy)

        merged_defaults = default_theme_config()

        # Fill Academy branding into defaults if empty
        if not merged_defaults.get("academy_name") and academy.name:
            merged_defaults["academy_name"] = academy.name

        if not settings.draft_config or not isinstance(settings.draft_config, dict):
            settings.draft_config = dict(merged_defaults)
            settings.save(update_fields=['draft_config'])
        else:
            # Backfill any missing fields
            updated = False
            for k, v in merged_defaults.items():
                if k not in settings.draft_config:
                    settings.draft_config[k] = v
                    updated = True
            if updated:
                settings.save(update_fields=['draft_config'])

        if not settings.published_config or not isinstance(settings.published_config, dict):
            settings.published_config = dict(settings.draft_config)
            settings.save(update_fields=['published_config'])

        return settings

    @classmethod
    def update_draft_config(cls, academy: Academy, data: dict, updated_by=None) -> WebsiteSettings:
        """
        Updates the draft_config JSON with strict field validation.
        Does NOT automatically change the live published site.
        """
        settings = cls.get_or_create_settings(academy)
        current_draft = dict(settings.draft_config or default_theme_config())

        # Validate color fields if present
        color_fields = ["primary_color", "secondary_color", "accent_color", "background_color", "surface_color", "text_color", "muted_text_color", "border_color"]
        for field in color_fields:
            if data.get(field):
                cls.validate_hex_color(data[field], field)
                current_draft[field] = data[field].upper()

        # Update text & configuration fields
        text_fields = [
            "academy_name", "academy_tagline", "hero_badge", "home_hero_title", "home_hero_subtitle",
            "hero_image_url", "hero_cta_label", "hero_secondary_cta_label", "courses_title",
            "courses_description", "contact_title", "contact_description", "whatsapp_number",
            "address", "business_hours", "body_font", "heading_font", "button_radius",
            "card_radius", "header_variant", "footer_variant"
        ]

        for field in text_fields:
            if field in data and data[field] is not None:
                val = str(data[field])
                if len(val) > 1000:
                    raise ValidationError({field: f"{field} exceeds maximum allowed length."})
                current_draft[field] = val

        # Also sync classic model fields if provided
        if "home_hero_title" in data:
            settings.home_hero_title = str(data["home_hero_title"])[:100]
        if "home_hero_subtitle" in data:
            settings.home_hero_subtitle = str(data["home_hero_subtitle"])[:250]
        if "courses_title" in data:
            settings.courses_title = str(data["courses_title"])[:100]
        if "courses_description" in data:
            settings.courses_description = str(data["courses_description"])[:500]
        if "contact_title" in data:
            settings.contact_title = str(data["contact_title"])[:100]
        if "contact_description" in data:
            settings.contact_description = str(data["contact_description"])[:500]

        settings.draft_config = current_draft
        settings.updated_by = updated_by
        settings.save()
        return settings

    @classmethod
    def publish_theme(cls, academy: Academy, updated_by=None) -> WebsiteSettings:
        """
        Atomically copies draft_config to published_config, updates Academy.theme_color,
        sets published_at timestamp, and invalidates public cache.
        """
        settings = cls.get_or_create_settings(academy)
        settings.published_config = dict(settings.draft_config)
        settings.published_at = timezone.now()
        settings.updated_by = updated_by
        settings.save(update_fields=['published_config', 'published_at', 'updated_by'])

        # Update primary theme color on Academy model
        primary_color = settings.published_config.get("primary_color", "#2563EB")
        if getattr(academy, 'theme_color', None) != primary_color:
            academy.theme_color = primary_color
            academy.save(update_fields=['theme_color'])

        # Invalidate public cache
        cache_key = f"academy:{academy.id}:website_config"
        cache.delete(cache_key)

        return settings

    @classmethod
    def get_public_website_config(cls, academy: Academy) -> dict:
        """
        Builds public website configuration JSON combining Academy branding and Published Theme.
        Caches payload for fast public reads.
        """
        cache_key = f"academy:{academy.id}:website_config"
        cached_config = cache.get(cache_key)
        if cached_config:
            return cached_config

        settings = cls.get_or_create_settings(academy)
        active_config = settings.published_config if settings.published_config else default_theme_config()

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        config = {
            "academy": {
                "name": active_config.get("academy_name") or academy.name,
                "slug": academy.slug,
                "logo": logo_url,
                "favicon": favicon_url,
                "theme_color": active_config.get("primary_color", "#2563EB"),
                "email": getattr(academy, 'email', '') or '',
                "phone": getattr(academy, 'phone', '') or ''
            },
            "theme": active_config,
            "home": {
                "hero_title": active_config.get("home_hero_title") or settings.home_hero_title,
                "hero_subtitle": active_config.get("home_hero_subtitle") or settings.home_hero_subtitle
            },
            "courses": {
                "title": active_config.get("courses_title") or settings.courses_title,
                "description": active_config.get("courses_description") or settings.courses_description
            },
            "contact": {
                "title": active_config.get("contact_title") or settings.contact_title,
                "description": active_config.get("contact_description") or settings.contact_description,
                "whatsapp_number": active_config.get("whatsapp_number", ""),
                "address": active_config.get("address", ""),
                "business_hours": active_config.get("business_hours", "")
            }
        }

        cache.set(cache_key, config, timeout=3600)
        return config

    @classmethod
    def get_student_branding(cls, user) -> dict:
        """
        Assembles student portal branding response (name, logo, favicon, theme_color, theme_config).
        """
        academy = getattr(user, 'academy', None)
        if not academy and hasattr(user, 'student_profile') and getattr(user.student_profile, 'academy', None):
            academy = user.student_profile.academy

        if not academy:
            return {
                "academy_name": "CubixSkill Academy",
                "logo": "",
                "favicon": "",
                "theme_color": "#2563EB",
                "theme": default_theme_config()
            }

        settings = cls.get_or_create_settings(academy)
        active_config = settings.published_config or settings.draft_config or default_theme_config()

        logo_url = academy.logo.url if getattr(academy, 'logo', None) else ""
        favicon_url = academy.favicon.url if getattr(academy, 'favicon', None) else ""

        return {
            "academy_name": active_config.get("academy_name") or academy.name,
            "logo": logo_url,
            "favicon": favicon_url,
            "theme_color": active_config.get("primary_color", "#2563EB"),
            "theme": active_config
        }
