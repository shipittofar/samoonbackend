"""Reconcile tenant activation status with active branch count."""
from django.db import migrations, models


def reconcile_tenant_activation(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Branch = apps.get_model("tenants", "Branch")

    for tenant in Tenant.objects.exclude(status="closed").iterator():
        has_branches = Branch.objects.filter(
            tenant_id=tenant.id,
            status="active",
            is_active=True,
        ).exists()
        desired = "active" if has_branches else "inactive"
        if tenant.status != desired:
            Tenant.objects.filter(pk=tenant.pk).update(status=desired)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0005_extend_owner"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("inactive", "Inactive"),
                    ("closed", "Closed"),
                ],
                default="inactive",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            reconcile_tenant_activation,
            migrations.RunPython.noop,
        ),
    ]
