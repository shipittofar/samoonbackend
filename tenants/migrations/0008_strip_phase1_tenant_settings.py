"""Remove Phase 1 duplicated/computed keys from Tenant.settings.

Does not copy values onto Branch and does not modify Branch rows.
Unrelated settings keys are preserved.
"""
from django.db import migrations


PHASE1_TOP_LEVEL_KEYS = frozenset({
    "currency",
    "language",
    "timezone",
    "time_zone",
})

PHASE1_ORDERING_KEYS = frozenset({
    "dineIn",
    "dine_in",
    "delivery",
    "takeaway",
    "onlinePayment",
    "online_payment",
})

PHASE1_MARKETPLACE_KEYS = frozenset({
    "cuisines",
    "amenities",
    "openNow",
    "branchCount",
    "primaryBranchSlug",
})


def strip_phase1_deprecated_tenant_settings(settings):
    if not isinstance(settings, dict):
        return {}

    cleaned = dict(settings)

    for key in PHASE1_TOP_LEVEL_KEYS:
        cleaned.pop(key, None)

    ordering = cleaned.get("ordering")
    if isinstance(ordering, dict):
        ordering = {
            key: value
            for key, value in ordering.items()
            if key not in PHASE1_ORDERING_KEYS
        }
        if ordering:
            cleaned["ordering"] = ordering
        else:
            cleaned.pop("ordering", None)

    features = cleaned.get("features")
    if isinstance(features, dict):
        features = dict(features)
        features.pop("reservations", None)
        if features:
            cleaned["features"] = features
        else:
            cleaned.pop("features", None)

    marketplace = cleaned.get("marketplace")
    if isinstance(marketplace, dict):
        marketplace = {
            key: value
            for key, value in marketplace.items()
            if key not in PHASE1_MARKETPLACE_KEYS
        }
        if marketplace:
            cleaned["marketplace"] = marketplace
        else:
            cleaned.pop("marketplace", None)

    return cleaned


def strip_phase1_keys_from_tenant_settings(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.iterator():
        original = tenant.settings or {}
        cleaned = strip_phase1_deprecated_tenant_settings(original)
        if cleaned != original:
            Tenant.objects.filter(pk=tenant.pk).update(settings=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0007_branch_cuisines_amenities"),
    ]

    operations = [
        migrations.RunPython(
            strip_phase1_keys_from_tenant_settings,
            migrations.RunPython.noop,
        ),
    ]
