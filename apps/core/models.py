import uuid

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

#--------------------------------------------------------------
# Exception Handler
#--------------------------------------------------------------

class BaseModel(models.Model):
    """
    Abstract base model providing UUID primary key and creation/update timestamps.
    Completely domain-independent.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

#--------------------------------------------------------------
# SlugMixin
#--------------------------------------------------------------

class SlugMixin(models.Model):
    """
    Mixin for models that require URL-safe slug fields.
    Supports automatic slug generation from 'name' or 'title' attributes if present.
    """
    slug = models.SlugField(max_length=255, db_index=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.slug:
            candidate = getattr(self, 'name', None) or getattr(self, 'title', None)
            if candidate:
                self.slug = slugify(candidate)
        super().save(*args, **kwargs)

#--------------------------------------------------------------
# ActiveMixin
#--------------------------------------------------------------

class ActiveMixin(models.Model):
    """
    Mixin for models requiring simple enable/disable state.
    """
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        abstract = True

#--------------------------------------------------------------
# StatusMixin
#--------------------------------------------------------------

class StatusMixin(models.Model):
    """
    Mixin for models requiring generic status tracking without hardcoding business choices.
    Business apps define their own default values and choices.
    """
    status = models.CharField(max_length=50, default='ACTIVE', db_index=True)

    class Meta:
        abstract = True

#--------------------------------------------------------------
# SoftDeleteMixin
#--------------------------------------------------------------

class SoftDeleteMixin(models.Model):
    """
    Mixin for models requiring soft-deletion behavior.
    """
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])

#--------------------------------------------------------------
# OrderMixin
#--------------------------------------------------------------

class OrderMixin(models.Model):
    """
    Mixin for models requiring manual integer-based ordering.
    """
    order_index = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        abstract = True

#--------------------------------------------------------------
# PublishMixin
#--------------------------------------------------------------

class PublishMixin(models.Model):
    """
    Mixin for models supporting publishing workflows.
    """
    is_published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def publish(self):
        self.is_published = True
        self.published_at = timezone.now()
        self.save(update_fields=['is_published', 'published_at'])

    def unpublish(self):
        self.is_published = False
        self.save(update_fields=['is_published'])
