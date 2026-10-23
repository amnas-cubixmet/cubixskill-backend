# Synchronize audit action choices with the current AuditAction enum.
# Database column type and existing data are preserved.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('audit_logs', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('ACADEMY_CREATED', 'Academy Created'),
            ('ACADEMY_UPDATED', 'Academy Updated'),
            ('ACADEMY_DISABLED', 'Academy Disabled'),
            ('USER_CREATED', 'User Created'),
            ('USER_ROLE_CHANGED', 'User Role Changed'),
            ('USER_ACTIVATED', 'User Activated'),
            ('USER_DEACTIVATED', 'User Deactivated'),
            ('PERMISSION_GRANTED', 'Permission Granted'),
            ('PERMISSION_REVOKED', 'Permission Revoked'),
            ('COURSE_CREATED', 'Course Created'),
            ('COURSE_UPDATED', 'Course Updated'),
            ('COURSE_PUBLISHED', 'Course Published'),
            ('COURSE_ARCHIVED', 'Course Archived'),
            ('COURSE_FEATURE_ENABLED', 'Course Feature Enabled'),
            ('COURSE_FEATURE_DISABLED', 'Course Feature Disabled'),
            ('STUDENT_UPDATED', 'Student Profile Updated'),
            ('ENROLLMENT_CREATED', 'Manual Enrollment Created'),
            ('ENROLLMENT_EXTENDED', 'Enrollment Access Extended'),
            ('ENROLLMENT_SUSPENDED', 'Enrollment Suspended'),
            ('ENROLLMENT_REVOKED', 'Enrollment Revoked'),
            ('CERTIFICATE_REVOKED', 'Certificate Revoked'),
            ('CERTIFICATE_REISSUED', 'Certificate Reissued'),
            ('LIVE_SESSION_CREATED', 'Live Session Created'),
            ('LIVE_SESSION_RESCHEDULED', 'Live Session Rescheduled'),
            ('LIVE_SESSION_CANCELLED', 'Live Session Cancelled'),
            ('DISCUSSION_MODERATED', 'Discussion Moderated'),
            ('CHAT_MESSAGE_REMOVED', 'Chat Message Removed'),
            ('LEAD_ASSIGNED', 'Lead Reassigned'),
            ('LEAD_STATUS_CHANGED', 'Lead Status Changed'),
            ('LEAD_CONVERTED', 'Lead Converted'),
            ('MANUAL_PAYMENT_APPROVED', 'Manual Payment Approved'),
            ('PAYMENT_REFUND_REQUESTED', 'Payment Refund Initiated'),
            ('COUPON_CREATED', 'Coupon Created'),
            ('COUPON_UPDATED', 'Coupon Updated'),
            ('COUPON_DISABLED', 'Coupon Disabled'),
            ('CREDIT_ADJUSTED', 'Manual Credit Adjustment'),
            ('CREDIT_ENTRY_REVERSED', 'Credit Ledger Entry Reversed'),
            ('STORAGE_CORRECTED', 'Storage Billing Corrected'),
            ('WEBSITE_SETTINGS_CHANGED', 'Website Settings Changed'),
            ('REPORT_EXPORTED', 'Sensitive Report Exported'),
            ('TICKET_CREATED', 'Support Ticket Created'),
            ('TICKET_UPDATED', 'Support Ticket Updated'),
            ('TICKET_REPLIED', 'Support Ticket Replied'),
                ],
                db_index=True,
                max_length=100,
            ),
        ),
    ]
