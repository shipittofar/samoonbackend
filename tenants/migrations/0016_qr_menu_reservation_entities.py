"""Extend QrEntityType for menu/reservation and backfill branch resource QRs.

Menu and reservation QRs are independent rows (entity_type menu|reservation)
whose entity_id is the Branch UUID. They are the storefront menu and
reservation-page resources — not MenuCategory/MenuItem rows and not
customer booking records.

Backfill is idempotent: skips (entity_type, entity_id) pairs that already
have an active QR. Batched at 500 rows. Does not modify tenant/branch QR rows.
"""
import secrets
import string

from django.db import migrations, models


ALPHABET = string.ascii_lowercase + string.digits
BATCH = 500


def _random_code(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def _allocate_code(QrCode) -> str:
    for _ in range(12):
        code = _random_code()
        if not QrCode.objects.filter(code=code).exists():
            return code
    raise RuntimeError("Unable to allocate a unique QR code during backfill")


def backfill_menu_reservation_qr_codes(apps, schema_editor):
    Branch = apps.get_model("tenants", "Branch")
    QrCode = apps.get_model("tenants", "QrCode")

    existing = set(
        QrCode.objects.filter(
            is_active=True,
            entity_type__in=("menu", "reservation"),
        ).values_list("entity_type", "entity_id")
    )

    for entity_type, destination_type in (
        ("menu", "menu"),
        ("reservation", "reservation"),
    ):
        rows = []
        for branch_id in Branch.objects.values_list("id", flat=True).iterator():
            if (entity_type, branch_id) in existing:
                continue
            rows.append(
                QrCode(
                    code=_allocate_code(QrCode),
                    entity_type=entity_type,
                    entity_id=branch_id,
                    destination_type=destination_type,
                    is_active=True,
                )
            )
            if len(rows) >= BATCH:
                QrCode.objects.bulk_create(rows)
                rows = []
        if rows:
            QrCode.objects.bulk_create(rows)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0015_alter_qrcode_destination_type_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="qrcode",
            name="entity_type",
            field=models.CharField(
                choices=[
                    ("tenant", "Tenant"),
                    ("branch", "Branch"),
                    ("menu", "Menu"),
                    ("reservation", "Reservation"),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_menu_reservation_qr_codes, noop_reverse),
    ]
