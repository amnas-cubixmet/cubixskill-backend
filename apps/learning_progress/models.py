from core.models import BaseModel
from django.db import models


class ProgressStatus(models.TextChoices):
    NOT_STARTED = 'NOT_STARTED', 'Not Started'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    COMPLETED = 'COMPLETED', 'Completed'

class CourseProgress(BaseModel):
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, related_name='course_progresses', null=True, blank=True)
    enrollment = models.ForeignKey('enrollments.Enrollment', on_delete=models.CASCADE, related_name='progress', null=True, blank=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='student_progresses', null=True, blank=True)

    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    total_lessons = models.PositiveIntegerField(default=0)
    completed_lessons = models.PositiveIntegerField(default=0)

    current_lesson = models.ForeignKey('lessons.Lesson', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    last_accessed_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)

    class Meta:
        db_table = 'course_progresses'
        unique_together = ('student', 'course')

class ModuleProgress(BaseModel):
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, null=True, blank=True)
    module = models.ForeignKey('modules.Module', on_delete=models.CASCADE, null=True, blank=True)
    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED)

    class Meta:
        db_table = 'module_progresses'
        unique_together = ('student', 'module')

class LessonProgress(BaseModel):
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, null=True, blank=True)
    lesson = models.ForeignKey('lessons.Lesson', on_delete=models.CASCADE, null=True, blank=True)
    course_progress = models.ForeignKey(CourseProgress, on_delete=models.CASCADE, related_name='lesson_progresses', null=True, blank=True)

    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED)
    completion_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    started_at = models.DateTimeField(auto_now_add=True)
    last_accessed_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'lesson_progresses'
        unique_together = ('student', 'lesson')

class MediaProgress(BaseModel):
    lesson_progress = models.OneToOneField(LessonProgress, on_delete=models.CASCADE, related_name='media_progress')

    position_seconds = models.PositiveIntegerField(default=0)
    watched_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(default=0)

    last_position_seconds = models.PositiveIntegerField(default=0)
    completion_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'media_progresses'

class LearningActivity(BaseModel):
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, null=True, blank=True)
    lesson = models.ForeignKey('lessons.Lesson', on_delete=models.CASCADE, null=True, blank=True)
    activity_type = models.CharField(max_length=50)
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = 'learning_activities'
