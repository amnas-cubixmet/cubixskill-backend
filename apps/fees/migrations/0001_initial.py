import django.utils.timezone
from django.db import migrations, models

class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('payments', '0002_feeinstallment_coursedefaultfeeplan_feepayment_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='CourseDefaultFeePlan',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        ('plan_type', models.CharField(default='ONE_TIME', max_length=20)),
                        ('total_fee', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                        ('currency', models.CharField(default='INR', max_length=10)),
                        ('number_of_installments', models.PositiveIntegerField(default=1)),
                        ('start_date', models.DateField(default=django.utils.timezone.now)),
                        ('custom_installments', models.JSONField(blank=True, default=list)),
                        ('notes', models.TextField(blank=True, default='')),
                        ('course', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='default_fee_plan', to='courses.course')),
                    ],
                    options={
                        'db_table': 'course_default_fee_plans',
                    },
                ),
            ]
        )
    ]
