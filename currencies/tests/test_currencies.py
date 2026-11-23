from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from access.tests.helpers import make_tenant, make_user
from currencies import services
from currencies.models import Currency, CurrencyRateChange
from menu.models import MenuCategory, MenuItem
from orders.models import OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from orders.tests.test_console_websocket import make_branch, make_tenant_with_owner


def set_rate(code, rate, enabled=True):
    Currency.objects.filter(code=code).update(rate=Decimal(rate), enabled=enabled)
    services.invalidate()


class ConversionTests(TestCase):
    def setUp(self):
        cache.clear()
        set_rate("USD", "600000")   # 1 USD = 600,000 toman
        set_rate("EUR", "650000")

    def test_seeded_base_is_toman(self):
        self.assertEqual(services.base_code(), "IRT")
        self.assertTrue(Currency.objects.get(code="IRT").is_base)

    def test_convert_and_round_to_each_currency_step(self):
        # 200,000 toman -> USD: 0.3333 -> rounded to 0.10 step -> 0.30
        self.assertEqual(services.convert("200000", "IRT", "USD"), Decimal("0.30"))
        # 3 USD -> toman: 1,800,000 (step 1000)
        self.assertEqual(services.convert("3", "USD", "IRT"), Decimal("1800000"))
        # USD -> EUR goes through the base: 3 * 600000 / 650000 = 2.769 -> 2.80
        self.assertEqual(services.convert("3", "USD", "EUR"), Decimal("2.80"))
        self.assertEqual(services.convert("123456", "IRT", "IRT"), Decimal("123456"))

    def test_tax_and_fees_round_to_decimals_not_the_price_step(self):
        # 7,200 toman tax = $0.012: a price would round to 0.00 on the 0.10 step.
        self.assertEqual(services.convert("7200", "IRT", "USD", use_step=False), Decimal("0.01"))
        self.assertEqual(services.convert("7200", "IRT", "USD"), Decimal("0.00"))

    def test_no_rate_means_not_convertible(self):
        self.assertIsNone(services.convert("100", "IRT", "GBP"))  # seeded without a rate

    def test_explicit_price_wins(self):
        explicit = {"USD": "3.00"}
        self.assertEqual(services.price_in(base_price="200000", source="IRT", explicit=explicit, target="USD"), Decimal("3.00"))
        # No explicit EUR: converted from the base price
        self.assertEqual(services.price_in(base_price="200000", source="IRT", explicit=explicit, target="EUR"), Decimal("0.30"))

    def test_clean_explicit_prices(self):
        from rest_framework.exceptions import ValidationError

        self.assertEqual(services.clean_explicit_prices({"usd": "3", "IRT": "1"}, source="IRT"), {"USD": "3.00"})
        with self.assertRaises(ValidationError):
            services.clean_explicit_prices({"XXX": "1"}, source="IRT")
        with self.assertRaises(ValidationError):
            services.clean_explicit_prices({"USD": "-1"}, source="IRT")


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.root = make_user(is_superuser=True, is_staff=True)
        self.client = APIClient()

    def test_public_list_shows_enabled_only(self):
        body = APIClient().get("/api/currencies/").json()
        self.assertEqual(body["base"], "IRT")
        self.assertEqual([c["code"] for c in body["currencies"]], ["IRT"])

    def test_superuser_sets_rate_then_enables_with_history(self):
        self.client.force_authenticate(self.root)
        res = self.client.patch("/api/currencies/USD/", {"enabled": True}, format="json")
        self.assertEqual(res.status_code, 400)  # no rate yet
        res = self.client.patch("/api/currencies/USD/", {"rate": "610000", "reason": "Market"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        res = self.client.patch("/api/currencies/USD/", {"enabled": True}, format="json")
        self.assertTrue(res.json()["enabled"])
        self.assertEqual([c["code"] for c in APIClient().get("/api/currencies/").json()["currencies"]], ["IRT", "USD"])
        hist = self.client.get("/api/currencies/history/", {"code": "USD"}).json()["results"]
        self.assertEqual(hist[0]["newRate"], "610000")
        self.assertEqual(hist[0]["reason"], "Market")
        self.assertEqual(services.convert("3", "USD", "IRT"), Decimal("1830000"))  # cache refreshed

    def test_base_rate_cannot_change_and_non_superusers_are_refused(self):
        self.client.force_authenticate(self.root)
        self.client.patch("/api/currencies/IRT/", {"rate": "5", "enabled": False}, format="json")
        irt = Currency.objects.get(code="IRT")
        self.assertTrue(irt.enabled or irt.is_base)
        self.assertFalse(CurrencyRateChange.objects.filter(currency=irt).exists())
        owner, _ = make_tenant()
        self.client.force_authenticate(owner)
        self.assertEqual(self.client.patch("/api/currencies/USD/", {"rate": "1"}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/currencies/", {"code": "JPY"}, format="json").status_code, 403)

    def test_superuser_adds_a_currency(self):
        self.client.force_authenticate(self.root)
        res = self.client.post("/api/currencies/", {"code": "cad", "name": "Canadian Dollar", "rate": "430000"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["code"], "CAD")


class MenuAndOrderTests(TestCase):
    def setUp(self):
        cache.clear()
        set_rate("USD", "600000")
        set_rate("EUR", "650000")
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant, currency="IRT", ordering_enabled=True)
        cat = MenuCategory.objects.create(branch=self.branch, name="Coffee")
        self.espresso = MenuItem.objects.create(
            branch=self.branch, category=cat, name="Espresso", price=Decimal("200000"), prices={"USD": "3.00"}
        )
        self.customer = make_user()

    def test_menu_item_carries_currency_and_explicit_prices(self):
        from menu.api.serializers.response.item import MenuItemOutputSerializer

        data = MenuItemOutputSerializer(self.espresso).data
        self.assertEqual(data["currency"], "IRT")
        self.assertEqual(data["prices"], {"USD": "3.00"})

    def test_owner_sets_explicit_prices_through_the_api(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/menu/{self.branch.id}/categories/{self.espresso.category_id}/items/{self.espresso.id}/"
        res = client.patch(url, {"prices": {"usd": "3.5", "EUR": ""}}, format="json")
        if res.status_code == 405:  # detail alias route
            res = client.patch(f"/api/menu/items/{self.espresso.id}/?branch_id={self.branch.id}", {"prices": {"usd": "3.5"}}, format="json")
        self.assertIn(res.status_code, (200, 201), res.content)
        self.espresso.refresh_from_db()
        self.assertEqual(self.espresso.prices, {"USD": "3.50"})

    def test_multipart_update_without_prices_keeps_them(self):
        """A form update (e.g. with an image) that does not send prices must
        not erase the owner's per-currency prices."""
        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/menu/items/{self.espresso.id}/?branch_id={self.branch.id}"
        res = client.patch(url, {"name": "Espresso Doppio"}, format="multipart")
        self.assertIn(res.status_code, (200, 201), res.content)
        self.espresso.refresh_from_db()
        self.assertEqual(self.espresso.name, "Espresso Doppio")
        self.assertEqual(self.espresso.prices, {"USD": "3.00"})
        # And a form that does send them (as JSON text) still sets them.
        res = client.patch(url, {"prices": '{"USD": "4"}'}, format="multipart")
        self.assertIn(res.status_code, (200, 201), res.content)
        self.espresso.refresh_from_db()
        self.assertEqual(self.espresso.prices, {"USD": "4.00"})

    def _order(self, display_currency):
        return OrdersBusinessLogicLayer().create_order(
            customer=self.customer,
            validated_data={
                "branch_id": self.branch.id,
                "order_type": OrderType.PICKUP,
                "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": self.espresso.id, "quantity": 2}],
                "display_currency": display_currency,
            },
        )

    def test_order_snapshots_the_display_currency(self):
        order = self._order("USD")
        self.assertEqual(order.currency, "IRT")
        self.assertEqual(order.total, Decimal("400000"))  # charged in toman
        self.assertEqual(order.display_currency, "USD")
        self.assertEqual(order.display_total, Decimal("6.00"))  # 2 x explicit 3.00
        self.assertEqual(order.exchange_rates, {"IRT": "1", "USD": "600000.00000000"})

    def test_order_converts_where_no_explicit_price(self):
        order = self._order("EUR")
        self.assertEqual(order.display_currency, "EUR")
        self.assertEqual(order.display_total, Decimal("0.60"))  # 400000 / 650000 = 0.615 -> 0.60

    def test_unknown_or_disabled_display_currency_is_ignored(self):
        for code in ("GBP", "XXX", "", "IRT"):
            order = self._order(code)
            self.assertEqual(order.display_currency, "")
            self.assertIsNone(order.display_total)
