from django.db import models
from core.models import BaseModel

# --------------------------------------------------------------
# Website Settings
# Website is intentionally minimal: HOME, COURSES, CONTACT.
# Reuse Academy branding such as logo, favicon, and theme_color.
# Website content is Academy-scoped and must respect tenant isolation.
# Keep frontend layout separate from backend content/settings.
# Do not turn this app into a CMS, page builder, or SEO engine.
# Public endpoints must expose only safe published website data.
# --------------------------------------------------------------

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
