"""Add branch cuisines/amenities and backfill from tenant marketplace settings."""
from django.db import migrations, models


def copy_tenant_marketplace_cuisines_amenities_to_all_branches(apps, schema_editor):
    """Copy tenant.settings.marketplace cuisines/amenities to every branch."""
    Tenant = apps.get_model("tenants", "Tenant")
    Branch = apps.get_model("tenants", "Branch")

    for tenant in Tenant.objects.all().iterator():
        marketplace = (tenant.settings or {}).get("marketplace") or {}
        cuisines = marketplace.get("cuisines")
        amenities = marketplace.get("amenities")

        update_kwargs = {}
        if cuisines is not None:
            update_kwargs["cuisines"] = cuisines
        if amenities is not None:
            update_kwargs["amenities"] = amenities
        if update_kwargs:
            Branch.objects.filter(tenant_id=tenant.id).update(**update_kwargs)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0006_tenant_activation_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="branch",
            name="amenities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="branch",
            name="cuisines",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(
            copy_tenant_marketplace_cuisines_amenities_to_all_branches,
            migrations.RunPython.noop,
        ),
    ]
