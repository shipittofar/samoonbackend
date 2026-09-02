"""Add independent Tenant discover images and Branch hero image.

Does not copy or fall back existing logo/cover/hero values.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0010_strip_phase4a_features_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="discover_avatar",
            field=models.ImageField(
                blank=True, null=True, upload_to="tenant_discover_avatars/",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="discover_cover",
            field=models.ImageField(
                blank=True, null=True, upload_to="tenant_discover_covers/",
            ),
        ),
        migrations.AddField(
            model_name="branch",
            name="hero_image",
            field=models.ImageField(
                blank=True, null=True, upload_to="branch_heroes/",
            ),
        ),
    ]
