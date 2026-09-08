from core.models import ActiveMixin, BaseModel, OrderMixin, PublishMixin, SlugMixin
from django.db import models
from django.utils.text import slugify
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
# Course Language Model
#--------------------------------------------------------------

class CourseLanguage(BaseModel, SlugMixin, ActiveMixin, OrderMixin):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='course_languages', null=True, blank=True)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, blank=True, default='')

    class Meta:
        db_table = 'course_languages'
        unique_together = ('academy', 'slug')
        ordering = ['order_index', 'name']

    def __str__(self):
        return f"{self.name} ({self.academy.name if self.academy else 'Global'})"

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip().title()
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            count = 1
            while CourseLanguage.objects.filter(academy=self.academy, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

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
        return f"{self.name} ({self.academy.name if self.academy else 'Global'})"

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
# Category Alias System
#--------------------------------------------------------------

class CategoryAlias(BaseModel, SlugMixin):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='category_aliases', null=True, blank=True)
    canonical_category = models.ForeignKey(CourseCategory, on_delete=models.CASCADE, related_name='aliases')
    name = models.CharField(max_length=100)
    created_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'category_aliases'
        unique_together = ('academy', 'slug')

    def __str__(self):
        return f"{self.name} -> {self.canonical_category.name}"

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            count = 1
            while CategoryAlias.objects.filter(academy=self.academy, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

#--------------------------------------------------------------
# Category Merge Audit Log
#--------------------------------------------------------------

class CategoryMergeAudit(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='category_merges', null=True, blank=True)
    source_category_name = models.CharField(max_length=100)
    target_category = models.ForeignKey(CourseCategory, on_delete=models.CASCADE, related_name='merge_audits')
    courses_reassigned_count = models.IntegerField(default=0)
    merged_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True)
    merged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'category_merge_audits'
        ordering = ['-merged_at']

    def __str__(self):
        return f"Merged '{self.source_category_name}' -> '{self.target_category.name}'"


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
    thumbnail_url = models.URLField(max_length=500, blank=True, default='')
    promo_video = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, null=True, blank=True, related_name='course_promo_videos')
    promo_video_url = models.URLField(max_length=500, blank=True, default='')


    level = models.CharField(max_length=20, choices=CourseLevel.choices, default=CourseLevel.ALL_LEVELS)
    language = models.CharField(max_length=50, default='English')
    duration_minutes = models.PositiveIntegerField(default=0)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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
        return f"{self.title} ({self.academy.name if self.academy else 'Global'})"

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
            self.sale_price = None
        else:
            if self.sale_price is not None and self.price is not None:
                if self.sale_price >= self.price:
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError({"sale_price": ["Sale price must be lower than the regular price."]})

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
