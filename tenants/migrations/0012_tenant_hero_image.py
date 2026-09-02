"""Add Tenant.hero_image and stop using settings.marketplace.heroImage.

Does not copy marketplace URLs or Branch images onto the new field.
"""
from django.db import migrations, models


HERO_MARKETPLACE_KEY = "heroImage"


def strip_marketplace_hero_image(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.iterator():
        original = tenant.settings or {}
        if not isinstance(original, dict):
            continue
        marketplace = original.get("marketplace")
        if not isinstance(marketplace, dict) or HERO_MARKETPLACE_KEY not in marketplace:
            continue
        marketplace = dict(marketplace)
        marketplace.pop(HERO_MARKETPLACE_KEY, None)
        cleaned = dict(original)
        if marketplace:
            cleaned["marketplace"] = marketplace
        else:
            cleaned.pop("marketplace", None)
        if cleaned != original:
            Tenant.objects.filter(pk=tenant.pk).update(settings=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0011_tenant_discover_images_branch_hero"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="hero_image",
            field=models.ImageField(
                blank=True, null=True, upload_to="tenant_heroes/",
            ),
        ),
        migrations.RunPython(
            strip_marketplace_hero_image,
            migrations.RunPython.noop,
        ),
    ]
