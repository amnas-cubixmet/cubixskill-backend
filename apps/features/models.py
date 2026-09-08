from core.models import ActiveMixin, BaseModel
from django.db import models

#--------------------------------------------------------------
# FeatureScope Enum
#--------------------------------------------------------------

class FeatureScope(models.TextChoices):
    COURSE = 'COURSE', 'Course'
    PLATFORM_UI = 'PLATFORM_UI', 'Platform UI'

#--------------------------------------------------------------
# Feature
#--------------------------------------------------------------

class Feature(BaseModel, ActiveMixin):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100, unique=True, db_index=True)  # e.g., chat, course_reports
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, default='GENERAL')
    scope = models.CharField(
        max_length=20,
        choices=FeatureScope.choices,
        default=FeatureScope.COURSE
    )
    frontend_key = models.CharField(max_length=100, blank=True, default='')
    frontend_route = models.CharField(max_length=255, blank=True, default='')
    icon_key = models.CharField(max_length=100, blank=True, default='')
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'features'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.code})"

#--------------------------------------------------------------
# CourseFeature
#--------------------------------------------------------------

class CourseFeature(BaseModel):
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='course_features', null=True, blank=True)
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name='course_mappings', null=True, blank=True)


    is_enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    enabled_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    enabled_at = models.DateTimeField(auto_now_add=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'course_features'
        unique_together = ('course', 'feature')
        ordering = ['-created_at']

    def __str__(self):
        return f"Course {self.course_id} - Feature {self.feature.code}: {'ON' if self.is_enabled else 'OFF'}"

