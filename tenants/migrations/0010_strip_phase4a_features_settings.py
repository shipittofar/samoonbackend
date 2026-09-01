"""Remove unused Tenant.settings.features (Phase 4A).

Does not copy values onto Branch. Preserves featureFlags and other keys.
"""
from django.db import migrations


def strip_features_object(settings):
    if not isinstance(settings, dict):
        return {}
    cleaned = dict(settings)
    cleaned.pop("features", None)
    return cleaned


def strip_features_from_tenant_settings(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.iterator():
        original = tenant.settings or {}
        cleaned = strip_features_object(original)
        if cleaned != original:
            Tenant.objects.filter(pk=tenant.pk).update(settings=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0009_strip_phase2_marketplace_settings"),
    ]

    operations = [
        migrations.RunPython(
            strip_features_from_tenant_settings,
            migrations.RunPython.noop,
        ),
    ]
