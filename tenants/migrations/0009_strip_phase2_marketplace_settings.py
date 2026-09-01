"""Remove Phase 2 Branch-owned / derived keys from Tenant.settings.marketplace.

Does not copy values onto Branch and does not modify Branch rows.
Listing-only marketplace keys are preserved.
"""
from django.db import migrations


PHASE2_MARKETPLACE_KEYS = frozenset({
    "city",
    "email",
    "phone_number",
    "description",
    "coverImage",
    "branches",
})


def strip_phase2_marketplace_keys(settings):
    if not isinstance(settings, dict):
        return {}

    cleaned = dict(settings)
    marketplace = cleaned.get("marketplace")
    if isinstance(marketplace, dict):
        marketplace = {
            key: value
            for key, value in marketplace.items()
            if key not in PHASE2_MARKETPLACE_KEYS
        }
        if marketplace:
            cleaned["marketplace"] = marketplace
        else:
            cleaned.pop("marketplace", None)
    return cleaned


def strip_phase2_keys_from_tenant_settings(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.iterator():
        original = tenant.settings or {}
        cleaned = strip_phase2_marketplace_keys(original)
        if cleaned != original:
            Tenant.objects.filter(pk=tenant.pk).update(settings=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0008_strip_phase1_tenant_settings"),
    ]

    operations = [
        migrations.RunPython(
            strip_phase2_keys_from_tenant_settings,
            migrations.RunPython.noop,
        ),
    ]
