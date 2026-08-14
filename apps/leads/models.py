import re
from django.db import models
from django.utils import timezone
from core.models import BaseModel, ActiveMixin

# --------------------------------------------------------------
# Lead Enums & Constants
# --------------------------------------------------------------

class LeadStatus(models.TextChoices):
    NEW = 'NEW', 'New'
    CONTACTED = 'CONTACTED', 'Contacted'
    INTERESTED = 'INTERESTED', 'Interested'
    QUALIFIED = 'QUALIFIED', 'Qualified'
    FOLLOW_UP = 'FOLLOW_UP', 'Follow Up'
    CONVERTED = 'CONVERTED', 'Converted'
    LOST = 'LOST', 'Lost'
    DISQUALIFIED = 'DISQUALIFIED', 'Disqualified'

class LeadPriority(models.TextChoices):
    LOW = 'LOW', 'Low'
    NORMAL = 'NORMAL', 'Normal'
    HIGH = 'HIGH', 'High'
    URGENT = 'URGENT', 'Urgent'

class LeadSource(models.TextChoices):
    WEBSITE = 'WEBSITE', 'Website'
    LANDING_PAGE = 'LANDING_PAGE', 'Landing Page'
    COURSE_ENQUIRY = 'COURSE_ENQUIRY', 'Course Enquiry'
    MANUAL = 'MANUAL', 'Manual Entry'
    PHONE = 'PHONE', 'Phone'
    WHATSAPP = 'WHATSAPP', 'WhatsApp'
    EMAIL = 'EMAIL', 'Email'
    SOCIAL_MEDIA = 'SOCIAL_MEDIA', 'Social Media'
    REFERRAL = 'REFERRAL', 'Referral'
    IMPORT = 'IMPORT', 'Import'
    WALK_IN = 'WALK_IN', 'Walk In'
    OTHER = 'OTHER', 'Other'

class FollowUpType(models.TextChoices):
    CALL = 'CALL', 'Call'
    EMAIL = 'EMAIL', 'Email'
    WHATSAPP = 'WHATSAPP', 'WhatsApp'
    MEETING = 'MEETING', 'Meeting'
    DEMO = 'DEMO', 'Demo'
    OTHER = 'OTHER', 'Other'

class FollowUpStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    MISSED = 'MISSED', 'Missed'

class InterestLevel(models.TextChoices):
    LOW = 'LOW', 'Low'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High'

class ImportJobStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'

# --------------------------------------------------------------
# Normalization Helpers
# Normalize contact values before duplicate comparison so formatting
# differences do not create duplicate Leads.
# --------------------------------------------------------------

def normalize_phone_number(phone: str) -> str:
    if not phone:
        return ''
    cleaned = re.sub(r'[^\d+]', '', phone.strip())
    return cleaned

def normalize_email_address(email: str) -> str:
    if not email:
        return ''
    return email.strip().lower()

# --------------------------------------------------------------
# 1. Lead Model
# Represents a prospective Student before account/enrollment conversion.
# Lead != Student; Lead is preserved as historical CRM data after conversion.
# --------------------------------------------------------------

class Lead(BaseModel, ActiveMixin):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='leads',
        null=True,
        blank=True
    )

    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=30, blank=True, default='')

    email_normalized = models.CharField(max_length=255, blank=True, default='', db_index=True)
    phone_normalized = models.CharField(max_length=30, blank=True, default='', db_index=True)

    status = models.CharField(
        max_length=20,
        choices=LeadStatus.choices,
        default=LeadStatus.NEW,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=LeadPriority.choices,
        default=LeadPriority.NORMAL,
        db_index=True
    )
    source = models.CharField(
        max_length=50,
        choices=LeadSource.choices,
        default=LeadSource.WEBSITE,
        db_index=True
    )
    source_detail = models.CharField(max_length=255, blank=True, default='')
    preferred_contact_method = models.CharField(max_length=30, default='EMAIL')

    # Lead.assigned_to stores the current assignee while LeadAssignment preserves history.
    assigned_to = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads'
    )

    next_follow_up_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)

    converted_user = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    converted_student = models.ForeignKey(
        'students.StudentProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    lost_reason = models.TextField(blank=True, default='')
    notes_summary = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'leads'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['academy', 'status']),
            models.Index(fields=['academy', 'assigned_to']),
            models.Index(fields=['academy', 'email_normalized']),
            models.Index(fields=['academy', 'phone_normalized']),
        ]

    def save(self, *args, **kwargs):
        self.email_normalized = normalize_email_address(self.email)
        self.phone_normalized = normalize_phone_number(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.status})"

# --------------------------------------------------------------
# 2. Lead Course Interest Model
# Allows one Lead to express interest in multiple Academy Courses.
# --------------------------------------------------------------

class LeadCourseInterest(BaseModel):
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='course_interests',
        null=True,
        blank=True
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    interest_level = models.CharField(
        max_length=20,
        choices=InterestLevel.choices,
        default=InterestLevel.MEDIUM
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'lead_course_interests'
        unique_together = ('lead', 'course')

    def __str__(self):
        return f"{self.lead.full_name} interested in {self.course.title if self.course else 'Course'}"

# --------------------------------------------------------------
# 3. Lead Assignment Model
# Preserves the history of staff assignment and reassignment.
# --------------------------------------------------------------

class LeadAssignment(BaseModel):
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='assignments',
        null=True,
        blank=True
    )
    assigned_to = models.ForeignKey(
        'users_roles.User',
        on_delete=models.CASCADE,
        related_name='+'
    )
    assigned_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    unassigned_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'lead_assignments'
        ordering = ['-assigned_at']

    def __str__(self):
        return f"Assignment: {self.lead.full_name} -> {self.assigned_to.email}"

# --------------------------------------------------------------
# 4. Lead Follow-Up Model
# Tracks scheduled CRM actions such as calls, email, WhatsApp, or meetings.
# --------------------------------------------------------------

class LeadFollowUp(BaseModel):
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='follow_ups',
        null=True,
        blank=True
    )
    follow_up_type = models.CharField(
        max_length=20,
        choices=FollowUpType.choices,
        default=FollowUpType.CALL
    )
    scheduled_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.PENDING,
        db_index=True
    )
    assigned_to = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    outcome = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        db_table = 'lead_follow_ups'
        ordering = ['scheduled_at']

    def __str__(self):
        return f"FollowUp [{self.follow_up_type}] for {self.lead.full_name} ({self.status})"

# --------------------------------------------------------------
# 5. Lead Note Model
# Stores internal Academy staff notes about a Lead.
# Internal CRM data; never exposed through public enquiry endpoints.
# --------------------------------------------------------------

class LeadNote(BaseModel):
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='notes',
        null=True,
        blank=True
    )
    content = models.TextField()
    author = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    is_pinned = models.BooleanField(default=False)

    class Meta:
        db_table = 'lead_notes'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"Note on {self.lead.full_name} by {self.author}"

# --------------------------------------------------------------
# 6. Lead Activity Model
# Maintains the detailed CRM activity timeline for this Lead.
# LeadActivity stores Lead-domain history; AuditLog is reserved for administrative actions.
# --------------------------------------------------------------

class LeadActivity(BaseModel):
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='activities',
        null=True,
        blank=True
    )
    activity_type = models.CharField(max_length=50, db_index=True)
    performed_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'lead_activities'
        ordering = ['-occurred_at']

    def __str__(self):
        return f"{self.activity_type} on {self.lead.full_name} at {self.occurred_at}"

# --------------------------------------------------------------
# 7. Lead Tag Model
# Categorizes Leads with custom Academy-scoped tags.
# --------------------------------------------------------------

class LeadTag(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='lead_tags',
        null=True,
        blank=True
    )
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, default='#3B82F6')
    leads = models.ManyToManyField(Lead, related_name='tags', blank=True)

    class Meta:
        db_table = 'lead_tags'
        unique_together = ('academy', 'name')

    def __str__(self):
        return f"Tag '{self.name}' ({self.academy.name if self.academy else 'Global'})"

# --------------------------------------------------------------
# 8. Lead Import Job Model
# Processes large Lead spreadsheet imports asynchronously.
# Import files reference MediaFile (local development storage).
# --------------------------------------------------------------

class LeadImportJob(BaseModel):
    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        related_name='lead_import_jobs',
        null=True,
        blank=True
    )
    uploaded_by = models.ForeignKey(
        'users_roles.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    source_media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=ImportJobStatus.choices,
        default=ImportJobStatus.PENDING,
        db_index=True
    )
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    error_report_media_file = models.ForeignKey(
        'storage.MediaFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'lead_import_jobs'
        ordering = ['-created_at']

    def __str__(self):
        return f"Import Job {self.id} for {self.academy.name if self.academy else 'Academy'} ({self.status})"
