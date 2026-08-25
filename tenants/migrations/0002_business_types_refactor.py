from django.db import migrations, models


def migrate_type_to_business_types(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.all().iterator():
        legacy_type = getattr(tenant, "type", None)
        if legacy_type == "coffee":
            tenant.business_types = ["cafe"]
        elif legacy_type == "restaurant":
            tenant.business_types = ["restaurant"]
        elif legacy_type:
            tenant.business_types = [legacy_type]
        else:
            tenant.business_types = []
        tenant.save(update_fields=["business_types"])


def migrate_business_types_json_values(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.all().iterator():
        values = tenant.business_types or []
        updated = False
        normalized = []
        for value in values:
            if value == "coffee":
                normalized.append("cafe")
                updated = True
            else:
                normalized.append(value)
        if updated:
            tenant.business_types = normalized
            tenant.save(update_fields=["business_types"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="business_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="tenant",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Quick active/inactive toggle for the tenant (independent of status)",
            ),
        ),
        migrations.RunPython(
            migrate_type_to_business_types,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            migrate_business_types_json_values,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="tenant",
            name="type",
        ),
    ]
