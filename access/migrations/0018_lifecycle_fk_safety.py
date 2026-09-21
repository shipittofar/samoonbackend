from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0017_alter_permissionaudit_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="permissionaudit",
            name="action",
            field=models.CharField(
                choices=[
                    ("role.created", "Role created"),
                    ("role.updated", "Role updated"),
                    ("role.deleted", "Role deleted"),
                    ("assignment.created", "Assignment created"),
                    ("assignment.updated", "Assignment updated"),
                    ("assignment.revoked", "Assignment revoked"),
                    ("override.created", "Override created"),
                    ("override.updated", "Override updated"),
                    ("override.removed", "Override removed"),
                    ("role.permissions_changed", "Role permissions changed"),
                    ("ownership.transferred", "Ownership transferred"),
                    ("membership.removed", "Membership removed"),
                    ("tenant.deactivated", "Tenant deactivated"),
                ],
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="permissionaudit",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="permission_audit_entries",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="staffmembership",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="staff_memberships",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="staffassignment",
            name="membership",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignments",
                to="access.staffmembership",
            ),
        ),
    ]
