from django.db import migrations
from django.utils import timezone


def verify_existing_addresses(apps, schema_editor):
    Address = apps.get_model("addresses", "Address")
    now = timezone.now()

    for address in Address.objects.all().iterator():
        verified_at = address.verified_at or address.created_at or now
        Address.objects.filter(pk=address.pk).update(
            verification_status="verified",
            is_verified=True,
            verified_at=verified_at,
            verification_source="system",
        )


def noop_reverse(apps, schema_editor):
    """Verification backfill is not reversed."""


class Migration(migrations.Migration):

    dependencies = [
        ("addresses", "0003_alter_address_label"),
    ]

    operations = [
        migrations.RunPython(verify_existing_addresses, noop_reverse),
    ]
