"""TON and XRP for crypto wallet top-ups (USDT is already seeded).

Disabled for price display until a superuser sets a rate; wallet balances in
them work regardless.
"""
from decimal import Decimal

from django.db import migrations

SEED = [
    ("TON", "Toncoin", "TON", 4, Decimal("0.0001"), 80),
    ("XRP", "XRP", "XRP", 4, Decimal("0.0001"), 90),
]


def seed(apps, schema_editor):
    Currency = apps.get_model("currencies", "Currency")
    for code, name, symbol, decimals, step, sort in SEED:
        Currency.objects.get_or_create(
            code=code,
            defaults={"name": name, "symbol": symbol, "decimals": decimals, "rounding_step": step, "sort_order": sort},
        )


def unseed(apps, schema_editor):
    apps.get_model("currencies", "Currency").objects.filter(code__in=[s[0] for s in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("currencies", "0002_seed_currencies")]

    operations = [migrations.RunPython(seed, unseed)]
