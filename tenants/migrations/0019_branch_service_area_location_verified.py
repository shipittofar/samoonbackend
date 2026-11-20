from django.db import migrations, models


class Migration(migrations.Migration):
    """Branch service area (JSON) and server-stamped pin verification time."""

    dependencies = [
        ('tenants', '0018_imagefield_max_length_512'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='service_area',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='branch',
            name='location_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
