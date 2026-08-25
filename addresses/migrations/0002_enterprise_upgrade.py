import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_label_to_address_type(apps, schema_editor):
    Address = apps.get_model("addresses", "Address")
    mapping = {
        "home": "home",
        "work": "work",
        "office": "office",
        "parents": "other",
        "custom": "other",
        "warehouse": "warehouse",
    }
    for address in Address.objects.all().iterator():
        old_label = (address.label or "home").lower()
        address.address_type = mapping.get(old_label, "other")
        if address.address_type == "other" and old_label not in mapping:
            address.custom_label = address.title or old_label
        if not address.verification_status:
            address.verification_status = "verified" if address.is_verified else "pending"
        address.save(update_fields=["address_type", "custom_label", "verification_status"])


class Migration(migrations.Migration):

    dependencies = [
        ("addresses", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="address",
            name="address_type",
            field=models.CharField(
                choices=[("home", "Home"), ("work", "Work"), ("office", "Office"), ("warehouse", "Warehouse"), ("other", "Other")],
                default="home",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="address",
            name="custom_label",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="address",
            name="floor",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="address",
            name="formatted_address",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="address",
            name="verification_status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("verified", "Verified"), ("rejected", "Rejected"), ("expired", "Expired")],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="address",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="address",
            name="verified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="verified_addresses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="address",
            name="verification_source",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(migrate_label_to_address_type, migrations.RunPython.noop),
        migrations.CreateModel(
            name="AddressAuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=32)),
                ("changed_fields", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="address_audit_actions", to=settings.AUTH_USER_MODEL)),
                ("address", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audit_logs", to="addresses.address")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="address_audit_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "address_audit_log",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["district"], name="user_address_district_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["formatted_address"], name="user_address_formatted_idx"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["verification_status"], name="user_address_verif_idx"),
        ),
        migrations.AddIndex(
            model_name="addressauditlog",
            index=models.Index(fields=["address"], name="addr_audit_address_idx"),
        ),
        migrations.AddIndex(
            model_name="addressauditlog",
            index=models.Index(fields=["user"], name="addr_audit_user_idx"),
        ),
        migrations.AddIndex(
            model_name="addressauditlog",
            index=models.Index(fields=["action"], name="addr_audit_action_idx"),
        ),
        migrations.AddIndex(
            model_name="addressauditlog",
            index=models.Index(fields=["created_at"], name="addr_audit_created_idx"),
        ),
    ]
