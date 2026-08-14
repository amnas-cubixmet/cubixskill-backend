from django.db import models
from django.utils import timezone
from core.models import BaseModel

#--------------------------------------------------------------
# AccessType
#--------------------------------------------------------------

class AccessType(models.TextChoices):
    FULL = 'FULL', 'Full Access'
    DEMO = 'DEMO', 'Demo Access'

#--------------------------------------------------------------
# EnrollmentStatus
#--------------------------------------------------------------

class EnrollmentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    ACTIVE = 'ACTIVE', 'Active'
    EXPIRED = 'EXPIRED', 'Expired'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    REVOKED = 'REVOKED', 'Revoked'
    CANCELLED = 'CANCELLED', 'Cancelled'

#--------------------------------------------------------------
# EnrollmentSource
#--------------------------------------------------------------

class EnrollmentSource(models.TextChoices):
    PURCHASE = 'PURCHASE', 'Purchase'
    MANUAL = 'MANUAL', 'Manual Admin'
    REGISTRATION = 'REGISTRATION', 'Registration'
    FREE_COURSE = 'FREE_COURSE', 'Free Course'
    DEMO = 'DEMO', 'Demo Trial'
    PROMOTION = 'PROMOTION', 'Promotional'
    IMPORT = 'IMPORT', 'Data Import'
    SYSTEM = 'SYSTEM', 'System Automated'
    LEAD_CONVERSION = 'LEAD_CONVERSION', 'Lead Conversion'

#--------------------------------------------------------------
# EnrollmentEventType
#--------------------------------------------------------------

class EnrollmentEventType(models.TextChoices):
    CREATED = 'CREATED', 'Enrollment Created'
    ACTIVATED = 'ACTIVATED', 'Enrollment Activated'
    DEMO_STARTED = 'DEMO_STARTED', 'Demo Started'
    UPGRADED_TO_FULL = 'UPGRADED_TO_FULL', 'Upgraded to Full Access'
    EXTENDED = 'EXTENDED', 'Access Extended'
    SUSPENDED = 'SUSPENDED', 'Access Suspended'
    RESUMED = 'RESUMED', 'Access Resumed'
    REVOKED = 'REVOKED', 'Access Revoked'
    CANCELLED = 'CANCELLED', 'Enrollment Cancelled'
    EXPIRED = 'EXPIRED', 'Access Expired'
    REACTIVATED = 'REACTIVATED', 'Enrollment Reactivated'

#--------------------------------------------------------------
# Enrollment Model
#--------------------------------------------------------------

class Enrollment(BaseModel):
    student = models.ForeignKey('users_roles.User', on_delete=models.CASCADE, related_name='enrollments', null=True, blank=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='enrollments', null=True, blank=True)

    access_type = models.CharField(max_length=20, choices=AccessType.choices, default=AccessType.FULL)
    status = models.CharField(max_length=20, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE, db_index=True)
    source = models.CharField(max_length=30, choices=EnrollmentSource.choices, default=EnrollmentSource.PURCHASE)

    enrolled_at = models.DateTimeField(default=timezone.now)
    access_starts_at = models.DateTimeField(default=timezone.now)
    access_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_lifetime = models.BooleanField(default=True)

    created_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    source_reference = models.CharField(max_length=255, blank=True, default='')

    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'enrollments'
        unique_together = ('student', 'course')
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['status', 'access_expires_at']),
            models.Index(fields=['access_type', 'status']),
        ]

    def __str__(self):
        student_email = self.student.email if self.student else 'Unknown Student'
        course_title = self.course.title if self.course else 'Unknown Course'
        return f"{student_email} enrolled in {course_title} ({self.access_type} - {self.status})"

    def is_currently_valid(self, at_time=None) -> bool:
        """Determines if access is currently valid based on status and dates."""
        if self.status != EnrollmentStatus.ACTIVE:
            return False
        now = at_time or timezone.now()
        if self.access_starts_at and now < self.access_starts_at:
            return False
        if not self.is_lifetime and self.access_expires_at and now >= self.access_expires_at:
            return False
        return True

#--------------------------------------------------------------
# EnrollmentAccessPeriod Model
#--------------------------------------------------------------

class EnrollmentAccessPeriod(BaseModel):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='access_periods', null=True, blank=True)
    access_type = models.CharField(max_length=20, choices=AccessType.choices, default=AccessType.FULL)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default='')
    granted_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    source_reference = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'enrollment_access_periods'
        ordering = ['-starts_at']

    def __str__(self):
        return f"AccessPeriod for Enrollment {self.enrollment_id} ({self.access_type}): {self.starts_at} to {self.expires_at}"

#--------------------------------------------------------------
# EnrollmentEvent Model
#--------------------------------------------------------------

class EnrollmentEvent(BaseModel):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    event_type = models.CharField(max_length=50, choices=EnrollmentEventType.choices, db_index=True)
    previous_status = models.CharField(max_length=20, blank=True, default='')
    new_status = models.CharField(max_length=20, blank=True, default='')
    occurred_at = models.DateTimeField(default=timezone.now)
    performed_by = models.ForeignKey('users_roles.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reason = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'enrollment_events'
        ordering = ['-occurred_at']

    def __str__(self):
        return f"EnrollmentEvent {self.event_type} for Enrollment {self.enrollment_id} at {self.occurred_at}"
