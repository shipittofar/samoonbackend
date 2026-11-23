"""Seed the platform base (Iranian toman) and common currencies.

Only the base is usable at first: the others have no exchange rate and stay
disabled until a platform superuser sets their rate (free-market rates are
entered by hand, not fetched).
"""
from decimal import Decimal

from django.db import migrations

SEED = [
    # code, name, symbol, decimals, rounding_step, sort, is_base
    ("IRT", "Toman", "تومان", 0, Decimal("1000"), 0, True),
    ("USD", "US Dollar", "$", 2, Decimal("0.10"), 10, False),
    ("EUR", "Euro", "€", 2, Decimal("0.10"), 20, False),
    ("AED", "UAE Dirham", "د.إ", 2, Decimal("0.50"), 30, False),
    ("TRY", "Turkish Lira", "₺", 2, Decimal("1"), 40, False),
    ("GBP", "Pound Sterling", "£", 2, Decimal("0.10"), 50, False),
    ("IQD", "Iraqi Dinar", "ع.د", 0, Decimal("250"), 60, False),
    ("USDT", "Tether (USDT)", "₮", 2, Decimal("0.01"), 70, False),
]


def seed(apps, schema_editor):
    Currency = apps.get_model("currencies", "Currency")
    for code, name, symbol, decimals, step, sort, is_base in SEED:
        Currency.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "symbol": symbol,
                "decimals": decimals,
                "rounding_step": step,
                "sort_order": sort,
                "is_base": is_base,
                "enabled": is_base,
                "rate": Decimal("1") if is_base else None,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("currencies", "Currency").objects.filter(code__in=[s[0] for s in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("currencies", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
