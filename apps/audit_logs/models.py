from core.models import BaseModel
from django.db import models
from django.utils import timezone
from users_roles.models import User

# --------------------------------------------------------------
# Audit Enums & Machine-Readable Constants
# --------------------------------------------------------------

class AuditCategory(models.TextChoices):
    ACADEMY = 'ACADEMY', 'Academy Management'
    AUTHENTICATION = 'AUTHENTICATION', 'Authentication & Security'
    USER = 'USER', 'User Administration'
    ROLE_PERMISSION = 'ROLE_PERMISSION', 'Role & Permissions'
    COURSE = 'COURSE', 'Course Management'
    ENROLLMENT = 'ENROLLMENT', 'Enrollment Administration'
    STUDENT = 'STUDENT', 'Student Administration'
    CERTIFICATE = 'CERTIFICATE', 'Certificates'
    LIVE_CLASS = 'LIVE_CLASS', 'Live Classes'
    COMMUNICATION = 'COMMUNICATION', 'Communication & Moderation'
    LEAD = 'LEAD', 'Lead CRM'
    PAYMENT = 'PAYMENT', 'Financial Payments'
    COUPON = 'COUPON', 'Coupons'
    CREDIT = 'CREDIT', 'Credit Wallet'
    STORAGE = 'STORAGE', 'Storage Billing & Management'
    WEBSITE = 'WEBSITE', 'Website Settings'
    REPORT = 'REPORT', 'Exported Reports'
    SECURITY = 'SECURITY', 'Security Incident'
    SYSTEM = 'SYSTEM', 'System Operation'

class AuditAction(models.TextChoices):
    # Academy
    ACADEMY_CREATED = 'ACADEMY_CREATED', 'Academy Created'
    ACADEMY_UPDATED = 'ACADEMY_UPDATED', 'Academy Updated'
    ACADEMY_DISABLED = 'ACADEMY_DISABLED', 'Academy Disabled'

    # User & Roles
    USER_CREATED = 'USER_CREATED', 'User Created'
    USER_ROLE_CHANGED = 'USER_ROLE_CHANGED', 'User Role Changed'
    USER_ACTIVATED = 'USER_ACTIVATED', 'User Activated'
    USER_DEACTIVATED = 'USER_DEACTIVATED', 'User Deactivated'
    PERMISSION_GRANTED = 'PERMISSION_GRANTED', 'Permission Granted'
    PERMISSION_REVOKED = 'PERMISSION_REVOKED', 'Permission Revoked'

    # Course & Features
    COURSE_CREATED = 'COURSE_CREATED', 'Course Created'
    COURSE_UPDATED = 'COURSE_UPDATED', 'Course Updated'
    COURSE_PUBLISHED = 'COURSE_PUBLISHED', 'Course Published'
    COURSE_ARCHIVED = 'COURSE_ARCHIVED', 'Course Archived'
    COURSE_FEATURE_ENABLED = 'COURSE_FEATURE_ENABLED', 'Course Feature Enabled'
    COURSE_FEATURE_DISABLED = 'COURSE_FEATURE_DISABLED', 'Course Feature Disabled'

    # Student & Enrollment Admin
    STUDENT_UPDATED = 'STUDENT_UPDATED', 'Student Profile Updated'
    ENROLLMENT_CREATED = 'ENROLLMENT_CREATED', 'Manual Enrollment Created'
    ENROLLMENT_EXTENDED = 'ENROLLMENT_EXTENDED', 'Enrollment Access Extended'
    ENROLLMENT_SUSPENDED = 'ENROLLMENT_SUSPENDED', 'Enrollment Suspended'
    ENROLLMENT_REVOKED = 'ENROLLMENT_REVOKED', 'Enrollment Revoked'

    # Certificates & Live Classes
    CERTIFICATE_REVOKED = 'CERTIFICATE_REVOKED', 'Certificate Revoked'
    CERTIFICATE_REISSUED = 'CERTIFICATE_REISSUED', 'Certificate Reissued'
    LIVE_SESSION_CREATED = 'LIVE_SESSION_CREATED', 'Live Session Created'
    LIVE_SESSION_RESCHEDULED = 'LIVE_SESSION_RESCHEDULED', 'Live Session Rescheduled'
    LIVE_SESSION_CANCELLED = 'LIVE_SESSION_CANCELLED', 'Live Session Cancelled'

    # Moderation & Leads
    DISCUSSION_MODERATED = 'DISCUSSION_MODERATED', 'Discussion Moderated'
    CHAT_MESSAGE_REMOVED = 'CHAT_MESSAGE_REMOVED', 'Chat Message Removed'
    LEAD_ASSIGNED = 'LEAD_ASSIGNED', 'Lead Reassigned'
    LEAD_STATUS_CHANGED = 'LEAD_STATUS_CHANGED', 'Lead Status Changed'
    LEAD_CONVERTED = 'LEAD_CONVERTED', 'Lead Converted'

    # Payments, Coupons, Credits
    MANUAL_PAYMENT_APPROVED = 'MANUAL_PAYMENT_APPROVED', 'Manual Payment Approved'
    PAYMENT_REFUND_REQUESTED = 'PAYMENT_REFUND_REQUESTED', 'Payment Refund Initiated'
    COUPON_CREATED = 'COUPON_CREATED', 'Coupon Created'
    COUPON_UPDATED = 'COUPON_UPDATED', 'Coupon Updated'
    COUPON_DISABLED = 'COUPON_DISABLED', 'Coupon Disabled'
    CREDIT_ADJUSTED = 'CREDIT_ADJUSTED', 'Manual Credit Adjustment'
    CREDIT_ENTRY_REVERSED = 'CREDIT_ENTRY_REVERSED', 'Credit Ledger Entry Reversed'

    # Storage, Website, Reports
    STORAGE_CORRECTED = 'STORAGE_CORRECTED', 'Storage Billing Corrected'
    WEBSITE_SETTINGS_CHANGED = 'WEBSITE_SETTINGS_CHANGED', 'Website Settings Changed'
    REPORT_EXPORTED = 'REPORT_EXPORTED', 'Sensitive Report Exported'

# --------------------------------------------------------------
# AuditLog Model
# AuditLog is append-only and should never be silently edited or deleted.
# Audit logs record important administrative and security actions.
# Domain history remains authoritative for its own business records.
# AuditLog should not duplicate every normal application event.
# Record actor, target, action, timestamp, and trusted request context.
# Academy-scoped audit data respects tenant isolation; Platform events use academy = null.
# --------------------------------------------------------------


class AuditLog(BaseModel):
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_actions'
    )
    actor_type = models.CharField(max_length=20, default='USER', db_index=True)  # USER, SYSTEM
    actor_display = models.CharField(max_length=255, blank=True, default='')
    actor_role = models.CharField(max_length=50, blank=True, default='')

    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    academy_display = models.CharField(max_length=255, blank=True, default='')

    action = models.CharField(
        max_length=100,
        choices=AuditAction.choices,
        db_index=True
    )
    category = models.CharField(
        max_length=50,
        choices=AuditCategory.choices,
        default=AuditCategory.SYSTEM,
        db_index=True
    )

    target_type = models.CharField(max_length=100, blank=True, default='', db_index=True)
    target_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    target_display = models.CharField(max_length=255, blank=True, default='')

    description = models.TextField(blank=True, default='')

    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    request_id = models.CharField(max_length=100, blank=True, default='', db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['academy', 'occurred_at']),
            models.Index(fields=['actor', 'occurred_at']),
            models.Index(fields=['action', 'occurred_at']),
            models.Index(fields=['category', 'occurred_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        actor_name = self.actor_display or (self.actor.email if self.actor else 'SYSTEM')
        return f"AuditLog [{self.action}] by {actor_name} at {self.occurred_at}"
