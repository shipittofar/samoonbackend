# Generated migration for checkout configuration refactor

from decimal import Decimal

from django.db import migrations, models
import django.core.validators
import tenants.checkout_config


def backfill_checkout_fields_from_settings(apps, schema_editor):
    Branch = apps.get_model("tenants", "Branch")
    mapping = tenants.checkout_config.JSON_KEY_TO_MODEL_FIELD

    for branch in Branch.objects.all().iterator():
        settings = branch.settings or {}
        if not settings:
            continue

        update_fields = []
        for json_key, model_field in mapping.items():
            if json_key not in settings:
                continue
            value = settings[json_key]
            if json_key == "minimumOrder" and value is not None:
                value = Decimal(str(value)).quantize(Decimal("0.01"))
            elif json_key in ("deliveryRadius", "maxCapacity") and value is not None:
                value = int(value)
            elif json_key in (
                "deliveryEnabled", "pickupEnabled", "tableOrderingEnabled",
                "orderingEnabled", "cashOnDeliveryEnabled", "sameDayDeliveryEnabled",
                "scheduledDeliveryEnabled", "contactlessDeliveryEnabled",
                "marketplaceVisible", "reservationsEnabled",
            ):
                value = bool(value)

            setattr(branch, model_field, value)
            update_fields.append(model_field)

        stripped = tenants.checkout_config.strip_operational_settings_keys(settings)
        if stripped != settings:
            branch.settings = stripped
            update_fields.append("settings")

        if update_fields:
            branch.save(update_fields=list(dict.fromkeys(update_fields)))


def strip_operational_settings_only(apps, schema_editor):
    """Ensure no operational keys remain after backfill."""
    Branch = apps.get_model("tenants", "Branch")
    for branch in Branch.objects.all().iterator():
        stripped = tenants.checkout_config.strip_operational_settings_keys(branch.settings or {})
        if stripped != (branch.settings or {}):
            branch.settings = stripped
            branch.save(update_fields=["settings"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0002_business_types_refactor"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="service_charge_percentage",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)],
                help_text="Service charge percentage applied to dine-in orders (e.g. 10 for 10%)",
            ),
        ),
        migrations.AddField(
            model_name="branch",
            name="ordering_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="delivery_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="pickup_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="table_ordering_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="default_order_type",
            field=models.CharField(
                blank=True,
                choices=[("delivery", "Delivery"), ("pickup", "Pickup"), ("dine_in", "Dine In")],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="branch",
            name="delivery_radius_km",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="minimum_order_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="same_day_delivery_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="scheduled_delivery_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="contactless_delivery_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="cash_on_delivery_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="cash_payment_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="card_payment_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="online_payment_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="wallet_payment_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="default_payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cash", "Cash"),
                    ("card", "Card"),
                    ("online", "Online"),
                    ("wallet", "Wallet"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="branch",
            name="marketplace_visible",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="branch",
            name="reservations_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="max_capacity",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="branch",
            name="settings",
            field=models.JSONField(blank=True, default=tenants.checkout_config.default_branch_settings),
        ),
        migrations.AddIndex(
            model_name="branch",
            index=models.Index(fields=["marketplace_visible"], name="branch_marketplace_visible_idx"),
        ),
        migrations.RunPython(backfill_checkout_fields_from_settings, migrations.RunPython.noop),
        migrations.RunPython(strip_operational_settings_only, migrations.RunPython.noop),
    ]
