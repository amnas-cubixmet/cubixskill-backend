from core.models import BaseModel
from django.db import models

# --------------------------------------------------------------
# Website Settings & Single Academy Theme Store
# Holds both draft_config and published_config for theme & text customization.
# Theme = ONE (shared by Public Website & Student Portal previews)
# --------------------------------------------------------------

def default_theme_config():
    return {
        "primary_color": "#2563EB",
        "secondary_color": "#0F172A",
        "accent_color": "#38BDF8",
        "background_color": "#F8FAFC",
        "surface_color": "#FFFFFF",
        "text_color": "#0F172A",
        "muted_text_color": "#64748B",
        "border_color": "#E2E8F0",
        "body_font": "Inter",
        "heading_font": "Inter",
        "button_radius": "12px",
        "card_radius": "16px",
        "header_variant": "default",
        "footer_variant": "default",
        "academy_name": "",
        "academy_tagline": "Software Engineering Academy",
        "hero_badge": "Official Public Academy • Live Cohorts",
        "home_hero_title": "Master Industry-Accredited Software Skills with Live Cohorts",
        "home_hero_subtitle": "Join thousands of developers mastering production-grade system architectures, microservices, and modern React 19 frameworks with 1-on-1 mentorship.",
        "hero_image_url": "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=900",
        "hero_cta_label": "Explore Accredited Courses",
        "hero_secondary_cta_label": "Book Demo Request",
        "courses_title": "Our Courses",
        "courses_description": "Explore our available courses.",
        "contact_title": "Contact Admissions & Support",
        "contact_description": "Get in touch with our team.",
        "whatsapp_number": "+1 (555) 019-9831",
        "address": "100 Innovation Parkway, Suite 400, Tech City",
        "business_hours": "Mon - Fri: 9:00 AM - 6:00 PM EST",
        "logo_url": "",
        "favicon_url": ""
    }

class WebsiteSettings(BaseModel):
    academy = models.OneToOneField(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='website_settings'
    )

    home_hero_title = models.CharField(
        max_length=100,
        default='Start Learning Today'
    )
    home_hero_subtitle = models.CharField(
        max_length=250,
        default='Explore our courses and build your skills.'
    )

    courses_title = models.CharField(
        max_length=100,
        default='Our Courses'
    )
    courses_description = models.TextField(
        max_length=500,
        default='Explore our available courses.'
    )

    contact_title = models.CharField(
        max_length=100,
        default='Contact Us'
    )
    contact_description = models.TextField(
        max_length=500,
        default='Get in touch with our team.'
    )

    # Durable Theme Storage: Draft & Published Configs
    draft_config = models.JSONField(
        default=default_theme_config,
        blank=True
    )
    published_config = models.JSONField(
        default=default_theme_config,
        blank=True
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True
    )

    updated_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'website_settings'

    def __str__(self):
        return f"WebsiteSettings for Academy {self.academy_id}"
