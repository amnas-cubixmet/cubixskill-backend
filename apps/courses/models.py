from django.db import models
from django.utils.text import slugify
from core.models import BaseModel, SlugMixin, ActiveMixin, PublishMixin, OrderMixin
from storage.models import MediaFile

#--------------------------------------------------------------
# Enums & Choices
#--------------------------------------------------------------

class CourseLevel(models.TextChoices):
    BEGINNER = 'BEGINNER', 'Beginner'
    INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
    ADVANCED = 'ADVANCED', 'Advanced'
    ALL_LEVELS = 'ALL_LEVELS', 'All Levels'

class CourseVisibility(models.TextChoices):
    PUBLIC = 'PUBLIC', 'Public'
    PRIVATE = 'PRIVATE', 'Private'
    UNLISTED = 'UNLISTED', 'Unlisted'

class CourseStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    PENDING_REVIEW = 'PENDING_REVIEW', 'Pending Review'
    PUBLISHED = 'PUBLISHED', 'Published'
    ARCHIVED = 'ARCHIVED', 'Archived'

#--------------------------------------------------------------
# Course Category Model
#--------------------------------------------------------------

class CourseCategory(BaseModel, SlugMixin, ActiveMixin, OrderMixin):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='course_categories', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'course_categories'
        unique_together = ('academy', 'slug')
        ordering = ['order_index', 'name']

    def __str__(self):
        return f"{self.name} ({self.academy.name})"

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            count = 1
            while CourseCategory.objects.filter(academy=self.academy, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

#--------------------------------------------------------------
# Primary Course Model
#--------------------------------------------------------------

class Course(BaseModel, SlugMixin, ActiveMixin, PublishMixin):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='courses', null=True, blank=True)
    category = models.ForeignKey(CourseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')

    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True, default='')
    short_description = models.TextField(blank=True, default='')
    description = models.TextField(blank=True, default='')

    thumbnail = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, null=True, blank=True, related_name='course_thumbnails')
    promo_video = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, null=True, blank=True, related_name='course_promo_videos')

    level = models.CharField(max_length=20, choices=CourseLevel.choices, default=CourseLevel.ALL_LEVELS)
    language = models.CharField(max_length=50, default='English')
    duration_minutes = models.PositiveIntegerField(default=0)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default='INR')
    is_free = models.BooleanField(default=False)

    visibility = models.CharField(max_length=20, choices=CourseVisibility.choices, default=CourseVisibility.PUBLIC)
    status = models.CharField(max_length=20, choices=CourseStatus.choices, default=CourseStatus.DRAFT, db_index=True)

    demo_enabled = models.BooleanField(default=False)
    demo_duration_days = models.PositiveIntegerField(default=0)
    certificate_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'courses'
        unique_together = ('academy', 'slug')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.academy.name})"

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base_slug = slugify(self.title)
            slug = base_slug
            count = 1
            while Course.objects.filter(academy=self.academy, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug

        if self.is_free:
            self.price = 0.00

        # Sync PublishMixin is_published with status
        if self.status == CourseStatus.PUBLISHED:
            self.is_published = True
        else:
            self.is_published = False

        super().save(*args, **kwargs)

#--------------------------------------------------------------
# Course Module Model
#--------------------------------------------------------------

class CourseModule(BaseModel, ActiveMixin, OrderMixin):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules', null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'course_modules'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"{self.title} - {self.course.title}"
