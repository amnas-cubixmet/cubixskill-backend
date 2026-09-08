from core.models import ActiveMixin, BaseModel, OrderMixin
from django.db import models

#--------------------------------------------------------------
# Primary Module Model
#--------------------------------------------------------------

class Module(BaseModel, ActiveMixin, OrderMixin):
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='course_modules', null=True, blank=True)

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    duration_minutes = models.PositiveIntegerField(default=0)
    is_demo = models.BooleanField(default=False)

    class Meta:
        db_table = 'modules'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"{self.course.title} - Module: {self.title}"
