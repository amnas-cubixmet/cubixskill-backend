from django.db import migrations, models
from django.utils.text import slugify


def populate_template_slugs(apps, schema_editor):
    CertificateTemplate = apps.get_model('certificates', 'CertificateTemplate')
    for template in CertificateTemplate.objects.all():
        if not template.slug:
            base_slug = slugify(template.name) or "certificate-template"
            slug_candidate = base_slug[:170]
            count = 1
            qs = CertificateTemplate.objects.filter(academy_id=template.academy_id).exclude(pk=template.pk)
            unique_slug = slug_candidate
            while qs.filter(slug=unique_slug).exists():
                count += 1
                unique_slug = f"{slug_candidate}-{count}"
            template.slug = unique_slug
            template.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('academy', '0006_academy_community_chat_file_upload_enabled'),
        ('certificates', '0005_remove_certificatefont_attribution_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='certificatetemplate',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=180),
        ),
        migrations.RunPython(populate_template_slugs, reverse_code=migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='certificatetemplate',
            unique_together={('academy', 'slug')},
        ),
    ]
