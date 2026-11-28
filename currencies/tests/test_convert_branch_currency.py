from decimal import Decimal
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.cache.key import CacheKeys
from currencies.models import Currency
from menu.models import Extra, ExtraGroup, MenuCategory, MenuItem, MenuItemExtra
from orders.tests.test_console_websocket import make_branch, make_tenant_with_owner


def run(*args):
    out = StringIO()
    call_command("convert_branch_currency", *args, stdout=out)
    return out.getvalue()


class ConvertBranchCurrencyTests(TestCase):
    def setUp(self):
        cache.clear()
        Currency.objects.filter(code="USD").update(rate=Decimal("90000"), enabled=True)
        _, self.tenant = make_tenant_with_owner()
        self.usd = make_branch(self.tenant, name="Old", currency="USD", minimum_order_amount=Decimal("10"))
        self.irt = make_branch(self.tenant, name="New", currency="IRT")
        cat = MenuCategory.objects.create(branch=self.usd, name="Coffee")
        self.espresso = MenuItem.objects.create(branch=self.usd, category=cat, name="Espresso", price=Decimal("3.00"))
        self.latte = MenuItem.objects.create(
            branch=self.usd, category=cat, name="Latte", price=Decimal("4.00"), prices={"IRT": "350000", "EUR": "3.50"}
        )
        group = ExtraGroup.objects.create(branch=self.usd, name="Size")
        self.large = Extra.objects.create(branch=self.usd, group=group, name="Large", price=Decimal("0.50"))
        self.link = MenuItemExtra.objects.create(item=self.espresso, extra=self.large, price_override=Decimal("0.75"))
        other_cat = MenuCategory.objects.create(branch=self.irt, name="Tea")
        self.tea = MenuItem.objects.create(branch=self.irt, category=other_cat, name="Tea", price=Decimal("80000"))

    def refresh(self):
        for obj in (self.usd, self.irt, self.espresso, self.latte, self.large, self.link, self.tea):
            obj.refresh_from_db()

    def test_report_only_writes_nothing(self):
        out = run("--from", "USD", "--to", "IRT")
        self.refresh()
        self.assertIn("REPORT ONLY", out)
        self.assertIn("1 branch(es) would be converted", out)
        self.assertEqual((self.usd.currency, self.espresso.price), ("USD", Decimal("3.00")))

    def test_apply_converts_and_keeps_the_old_price(self):
        out = run("--from", "USD", "--to", "IRT", "--apply")
        self.refresh()
        self.assertIn("1 branch(es) converted", out)
        self.assertEqual(self.usd.currency, "IRT")
        self.assertEqual(self.espresso.price, Decimal("270000"))
        self.assertEqual(self.espresso.prices, {"USD": "3.00"})  # a guest choosing dollars still pays 3.00
        # The owner's own toman price wins over the converted one.
        self.assertEqual(self.latte.price, Decimal("350000"))
        self.assertEqual(self.latte.prices, {"EUR": "3.50", "USD": "4.00"})
        self.assertEqual((self.large.price, self.link.price_override), (Decimal("45000"), Decimal("68000")))  # toman rounds to 1,000
        self.assertEqual(self.usd.minimum_order_amount, Decimal("900000"))
        self.assertEqual((self.irt.currency, self.tea.price), ("IRT", Decimal("80000")))  # untouched

    def test_explicit_rate_and_idempotent(self):
        run("--rate", "100000", "--apply")
        self.refresh()
        self.assertEqual(self.espresso.price, Decimal("300000"))
        self.assertIn("0 branch(es) converted", run("--rate", "100000", "--apply"))  # nothing left in USD
        self.refresh()
        self.assertEqual(self.espresso.price, Decimal("300000"))

    def test_too_large_amount_skips_the_whole_branch(self):
        MenuItem.objects.filter(pk=self.latte.pk).update(prices={})
        MenuItem.objects.filter(pk=self.espresso.pk).update(price=Decimal("5000"))
        out = run("--rate", "100000", "--apply")
        self.refresh()
        self.assertIn("SKIPPED", out)
        self.assertIn("Espresso", out)
        self.assertEqual((self.usd.currency, self.latte.price), ("USD", Decimal("4.00")))  # nothing half-done

    def test_only_selected_branch_and_bad_input(self):
        other = make_branch(self.tenant, name="Other", currency="USD")
        run("--branch", str(other.id), "--apply")
        self.refresh()
        other.refresh_from_db()
        self.assertEqual((other.currency, self.usd.currency), ("IRT", "USD"))
        for bad in (["--from", "IRT", "--to", "IRT"], ["--to", "XXX"], ["--rate", "-1"], ["--rate", "abc"]):
            with self.assertRaises(CommandError):
                run(*bad)

    def test_menu_cache_is_dropped(self):
        key = CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=self.usd.id)
        cache.set(key, ["stale"])
        with self.captureOnCommitCallbacks(execute=True):
            run("--apply")
        self.assertIsNone(cache.get(key))
