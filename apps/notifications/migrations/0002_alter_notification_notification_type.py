# Synchronize notification type choices with the current NotificationType enum.
# Database column type and existing data are preserved.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('LIVE_SESSION_CREATED', 'Live Session Created'),
            ('LIVE_SESSION_STARTING_SOON', 'Live Session Starting Soon'),
            ('LIVE_SESSION_CANCELLED', 'Live Session Cancelled'),
            ('COURSE_ENROLLED', 'Course Enrolled'),
            ('COURSE_COMPLETED', 'Course Completed'),
            ('PAYMENT_SUCCESS', 'Payment Success'),
            ('PAYMENT_FAILED', 'Payment Failed'),
            ('PAYMENT_REFUNDED', 'Payment Refunded'),
            ('CERTIFICATE_ISSUED', 'Certificate Issued'),
            ('LEAD_ASSIGNED', 'Lead Assigned'),
            ('LEAD_FOLLOW_UP_DUE', 'Lead Follow-Up Due'),
            ('CREDIT_BALANCE_LOW', 'Credit Balance Low'),
            ('CHAT_MENTION', 'Chat Mention'),
            ('DISCUSSION_REPLY', 'Discussion Reply'),
            ('ANNOUNCEMENT_PUBLISHED', 'Announcement Published'),
                ],
                db_index=True,
                default='LIVE_SESSION_STARTING_SOON',
                max_length=100,
            ),
        ),
    ]
