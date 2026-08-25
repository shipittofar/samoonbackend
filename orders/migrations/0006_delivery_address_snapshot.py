import hashlib
import uuid

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def _fingerprint(street, building_number, unit, city, postal_code, country):
    normalized = "|".join(
        part.strip().lower()
        for part in (street, building_number, unit, city, postal_code, country)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def migrate_legacy_addresses(apps, schema_editor):
    LegacyAddress = apps.get_model("orders", "Address")
    NewAddress = apps.get_model("addresses", "Address")
    Order = apps.get_model("orders", "Order")
    OrderDeliveryAddress = apps.get_model("orders", "OrderDeliveryAddress")
    User = apps.get_model("accounts", "User")

    legacy_to_snapshot = {}
    users_with_default = set()

    for legacy in LegacyAddress.objects.all().iterator():
        snapshot = OrderDeliveryAddress.objects.create(
            id=uuid.uuid4(),
            source_address_id=None,
            title=legacy.label or "Delivery",
            label=legacy.label or "",
            first_name="",
            last_name="",
            company="",
            phone="",
            country_code="",
            country="",
            province=legacy.state or "",
            city=legacy.city,
            district="",
            street=legacy.street,
            building_number="",
            unit="",
            postal_code=legacy.zip_code or "",
            latitude=legacy.lat,
            longitude=legacy.lng,
            delivery_notes="",
        )
        legacy_to_snapshot[legacy.id] = snapshot

        if legacy.user_id:
            user = User.objects.filter(pk=legacy.user_id).first()
            first_name = (user.first_name if user and user.first_name else "Customer")
            last_name = (user.last_name if user and user.last_name else "")
            phone = "0000000000"
            country_code = "+1"
            if user and user.phone_number:
                phone = "".join(ch for ch in user.phone_number if ch.isdigit())[-10:] or phone
            if user and user.country_code:
                country_code = user.country_code
            country = "US"
            postal = legacy.zip_code or "00000"
            fp = _fingerprint(legacy.street, "", "", legacy.city, postal, country)
            make_default = legacy.is_default and legacy.user_id not in users_with_default
            if make_default:
                users_with_default.add(legacy.user_id)
            NewAddress.objects.create(
                id=uuid.uuid4(),
                uuid=uuid.uuid4(),
                legacy_id=legacy.id,
                user_id=legacy.user_id,
                title=legacy.label or "Home",
                label="custom",
                first_name=first_name,
                last_name=last_name,
                company="",
                phone=phone,
                country_code=country_code,
                country=country,
                province=legacy.state or "",
                city=legacy.city,
                district="",
                street=legacy.street,
                building_number="",
                unit="",
                postal_code=postal,
                latitude=legacy.lat,
                longitude=legacy.lng,
                delivery_notes="",
                is_default=make_default,
                is_verified=False,
                verification_method="none",
                fingerprint=fp,
            )

    for order in Order.objects.exclude(delivery_address_id=None).iterator():
        snapshot = legacy_to_snapshot.get(order.delivery_address_id)
        if snapshot is not None:
            order.delivery_snapshot_id = snapshot.id
            order.save(update_fields=["delivery_snapshot_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_alter_order_status_alter_orderstatushistory_status"),
        ("addresses", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderDeliveryAddress",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_address_id", models.UUIDField(blank=True, help_text="Optional reference to the user address book entry that was snapshotted.", null=True)),
                ("title", models.CharField(blank=True, default="", max_length=100)),
                ("label", models.CharField(blank=True, default="", max_length=20)),
                ("first_name", models.CharField(blank=True, default="", max_length=64)),
                ("last_name", models.CharField(blank=True, default="", max_length=64)),
                ("company", models.CharField(blank=True, default="", max_length=128)),
                ("phone", models.CharField(blank=True, default="", max_length=20)),
                ("country_code", models.CharField(blank=True, default="", max_length=5)),
                ("country", models.CharField(blank=True, default="", max_length=2)),
                ("province", models.CharField(blank=True, default="", max_length=100)),
                ("city", models.CharField(max_length=100)),
                ("district", models.CharField(blank=True, default="", max_length=100)),
                ("street", models.CharField(max_length=500)),
                ("building_number", models.CharField(blank=True, default="", max_length=32)),
                ("unit", models.CharField(blank=True, default="", max_length=32)),
                ("postal_code", models.CharField(blank=True, default="", max_length=20)),
                ("latitude", models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)])),
                ("longitude", models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)])),
                ("delivery_notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "order_delivery_address",
            },
        ),
        migrations.AddIndex(
            model_name="orderdeliveryaddress",
            index=models.Index(fields=["source_address_id"], name="order_del_addr_source_idx"),
        ),
        migrations.AddIndex(
            model_name="orderdeliveryaddress",
            index=models.Index(fields=["created_at"], name="order_del_addr_created_idx"),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders_snapshot",
                to="orders.orderdeliveryaddress",
            ),
        ),
        migrations.RunPython(migrate_legacy_addresses, noop_reverse),
        migrations.RemoveField(
            model_name="order",
            name="delivery_address",
        ),
        migrations.RenameField(
            model_name="order",
            old_name="delivery_snapshot",
            new_name="delivery_address",
        ),
        migrations.AlterField(
            model_name="order",
            name="delivery_address",
            field=models.ForeignKey(
                blank=True,
                help_text="Immutable delivery address snapshot. Only set when order_type == delivery.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="orders.orderdeliveryaddress",
            ),
        ),
        migrations.DeleteModel(
            name="Address",
        ),
    ]
