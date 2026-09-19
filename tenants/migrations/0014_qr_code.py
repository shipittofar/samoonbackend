"""Create QrCode table and backfill identifiers for existing tenants/branches."""
import secrets
import string
import uuid

from django.db import migrations, models


ALPHABET = string.ascii_lowercase + string.digits


def _random_code(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def _allocate_code(QrCode) -> str:
    for _ in range(12):
        code = _random_code()
        if not QrCode.objects.filter(code=code).exists():
            return code
    raise RuntimeError("Unable to allocate a unique QR code during backfill")


def backfill_qr_codes(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Branch = apps.get_model("tenants", "Branch")
    QrCode = apps.get_model("tenants", "QrCode")

    existing = set(
        QrCode.objects.filter(is_active=True).values_list("entity_type", "entity_id")
    )

    tenant_rows = []
    for tenant_id in Tenant.objects.values_list("id", flat=True).iterator():
        if ("tenant", tenant_id) in existing:
            continue
        tenant_rows.append(
            QrCode(
                code=_allocate_code(QrCode),
                entity_type="tenant",
                entity_id=tenant_id,
                destination_type="tenant",
                is_active=True,
            )
        )
        if len(tenant_rows) >= 500:
            QrCode.objects.bulk_create(tenant_rows)
            tenant_rows = []
    if tenant_rows:
        QrCode.objects.bulk_create(tenant_rows)

    branch_rows = []
    for branch_id in Branch.objects.values_list("id", flat=True).iterator():
        if ("branch", branch_id) in existing:
            continue
        branch_rows.append(
            QrCode(
                code=_allocate_code(QrCode),
                entity_type="branch",
                entity_id=branch_id,
                destination_type="branch",
                is_active=True,
            )
        )
        if len(branch_rows) >= 500:
            QrCode.objects.bulk_create(branch_rows)
            branch_rows = []
    if branch_rows:
        QrCode.objects.bulk_create(branch_rows)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0013_tenant_description"),
    ]

    operations = [
        migrations.CreateModel(
            name="QrCode",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        serialize=False,
                        editable=False,
                    ),
                ),
                ("code", models.SlugField(max_length=32, unique=True)),
                ("entity_type", models.CharField(max_length=20)),
                ("entity_id", models.UUIDField()),
                ("destination_type", models.CharField(max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "qr_code",
            },
        ),
        migrations.AddIndex(
            model_name="qrcode",
            index=models.Index(
                fields=["entity_type", "entity_id"],
                name="qr_code_entity__idx",
            ),
        ),
        migrations.AddIndex(
            model_name="qrcode",
            index=models.Index(fields=["is_active"], name="qr_code_is_activ_idx"),
        ),
        migrations.AddConstraint(
            model_name="qrcode",
            constraint=models.UniqueConstraint(
                fields=("entity_type", "entity_id"),
                condition=models.Q(("is_active", True)),
                name="unique_active_qr_per_entity",
            ),
        ),
        migrations.RunPython(backfill_qr_codes, noop_reverse),
    ]
