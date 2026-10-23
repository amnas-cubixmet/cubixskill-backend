# Add public platform-level demo enquiries, independent from academy-scoped CRM leads.
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformDemoRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('full_name', models.CharField(max_length=255)),
                ('email', models.EmailField(max_length=254)),
                ('phone', models.CharField(max_length=30)),
                ('country', models.CharField(max_length=100)),
                ('academy_name', models.CharField(max_length=255)),
                ('student_count', models.CharField(max_length=30)),
                ('course_count', models.CharField(max_length=30)),
                ('current_platform', models.CharField(max_length=100)),
                ('main_requirement', models.CharField(max_length=500)),
                ('preferred_date', models.DateField()),
                ('preferred_time', models.TimeField()),
                ('time_zone', models.CharField(max_length=64)),
                ('message', models.TextField(blank=True, default='')),
                ('source', models.CharField(default='PUBLIC_WEBSITE', max_length=40)),
                ('status', models.CharField(db_index=True, default='NEW', max_length=20)),
            ],
            options={'db_table': 'platform_demo_requests', 'ordering': ['-created_at']},
        ),
    ]
