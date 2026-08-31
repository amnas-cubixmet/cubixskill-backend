from django.db import models
from django.utils.text import slugify
from core.models import BaseModel, SlugMixin, ActiveMixin
from storage.models import MediaFile

#--------------------------------------------------------------
# Operational Status Enum
#--------------------------------------------------------------

class AcademyStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    SUSPENDED = 'SUSPENDED', 'Suspended'

#--------------------------------------------------------------
# Academy Model
#--------------------------------------------------------------

class Academy(BaseModel, SlugMixin, ActiveMixin):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True, default='')

    # Branding & Theme Configuration
    theme = models.CharField(max_length=50, blank=True, default='default')
    theme_color = models.CharField(max_length=20, blank=True, default='#3B82F6')

    logo = models.ForeignKey(
        MediaFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='academy_logos'
    )
    favicon = models.ForeignKey(
        MediaFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='academy_favicons'
    )

    status = models.CharField(
        max_length=20,
        choices=AcademyStatus.choices,
        default=AcademyStatus.ACTIVE,
        db_index=True
    )

    # Demo & Trial Access Controls
    is_demo = models.BooleanField(default=False, db_index=True)
    demo_start_date = models.DateTimeField(null=True, blank=True)
    demo_expiry_date = models.DateTimeField(null=True, blank=True)

    # Access Duration
    access_start_date = models.DateTimeField(null=True, blank=True)
    access_end_date = models.DateTimeField(null=True, blank=True)

    # Feature Configuration
    feature_config = models.JSONField(default=dict, blank=True)

    # Video Processing & Streaming Configuration
    hls_video_enabled = models.BooleanField(default=True)

    # Personal Chat Configuration
    personal_chat_file_upload_enabled = models.BooleanField(default=True)

    # Community Chat Configuration
    community_chat_file_upload_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'academies'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_demo_status(self):
        from django.utils import timezone
        if not self.is_demo:
            return {
                "is_demo": False,
                "status": "NOT_DEMO",
                "is_expired": False,
                "days_remaining": None,
                "start_date": None,
                "expiry_date": None,
            }

        now = timezone.now()
        is_expired = bool(self.demo_expiry_date and now > self.demo_expiry_date)
        days_remaining = None
        if self.demo_expiry_date and not is_expired:
            days_remaining = max(0, (self.demo_expiry_date - now).days)

        return {
            "is_demo": True,
            "status": "EXPIRED" if is_expired else "ACTIVE",
            "is_expired": is_expired,
            "days_remaining": days_remaining,
            "start_date": self.demo_start_date.isoformat() if self.demo_start_date else None,
            "expiry_date": self.demo_expiry_date.isoformat() if self.demo_expiry_date else None,
        }

    def get_enabled_features(self):
        default_features = {
            "courses": True,
            "live_classes": True,
            "quizzes": True,
            "assignments": True,
            "certificates": True,
            "payments": True,
            "credits": True,
            "reports": True,
            "website_builder": True,
            "discussions": True,
            "media": True,
            "coupons": True,
            "demo_leads": True,
            "staff_management": True,
        }
        if isinstance(self.feature_config, dict):
            default_features.update(self.feature_config)
        return default_features

    def save(self, *args, **kwargs):
        # Derive unique URL-safe slug from name if empty
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            count = 1
            while Academy.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug

        # Sync operational status with active state cleanly
        if self.status == AcademyStatus.ACTIVE:
            self.is_active = True
        else:
            self.is_active = False

        super().save(*args, **kwargs)

