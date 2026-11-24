"""Settlement: commission, hold period, payouts. Every scenario ends with the
ledger health check (all transactions balance, balances match entries)."""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from menu.models import MenuCategory, MenuItem
from notifications.models import Notification
from orders.models import OrderStatus, OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from orders.tests.test_console_websocket import make_branch, make_tenant_with_owner, make_user
from platform_settings.models import PlatformSetting
from settlement import services
from settlement.models import OrderSettlement, Payout, PayoutAccount
from wallet import services as wallet
from wallet.models import AccountKind, WalletAccount
from wallet.tests.test_wallet import fund

IBAN = "IR820540102680020817909002"  # valid checksum
TRC20 = "TJYeasTPa6gpEEfYqfq6PJG6M1rMhEkSvR"
PICKUP_DONE = [OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY, OrderStatus.PICKED_UP]


def bal(tenant, kind=AccountKind.BUSINESS, currency="IRT"):
    a = WalletAccount.objects.filter(tenant=tenant, kind=kind, currency=currency).first()
    return a.balance if a else Decimal("0")


class Base(TestCase):
    def setUp(self):
        cache.clear()
        PlatformSetting.objects.update_or_create(
            key=services.SETTINGS_KEY,
            defaults={"value": {"commission_percent": "10", "hold_days": 3, "min_payout": {"IRT": "50000"}}},
        )
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(
            self.tenant, currency="IRT", ordering_enabled=True, wallet_payment_enabled=True, cash_payment_enabled=True
        )
        cat = MenuCategory.objects.create(branch=self.branch, name="Coffee")
        self.item = MenuItem.objects.create(branch=self.branch, category=cat, name="Espresso", price=Decimal("200000"))
        self.customer = make_user()
        self.root = make_user(is_superuser=True, is_staff=True)
        self.bll = OrdersBusinessLogicLayer()

    def order(self, method=PaymentMethod.WALLET):
        return self.bll.create_order(
            customer=self.customer,
            validated_data={
                "branch_id": self.branch.id, "order_type": OrderType.PICKUP, "payment_method": method,
                "items": [{"menu_item_id": self.item.id, "quantity": 1}],
            },
        )

    def finish(self, order):
        for status in PICKUP_DONE:
            self.bll.update_order_status(user=self.owner, public_id=order.id, new_status=status)
        return OrderSettlement.objects.get(order_id=order.id)

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def assertHealthy(self):
        self.assertTrue(wallet.health()["ok"], wallet.health()["problems"])


class CommissionAndHoldTests(Base):
    def test_wallet_order_commission_hold_and_release(self):
        fund(self.customer, "500000")
        order = self.order()
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_PENDING), Decimal("200000"))
        row = self.finish(order)
        self.assertEqual((row.commission, row.net, row.status), (Decimal("20000"), Decimal("180000"), "held"))
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_PENDING), Decimal("180000"))
        self.assertEqual(bal(self.tenant), 0)
        revenue = WalletAccount.objects.get(kind=AccountKind.SYSTEM_REVENUE, currency="IRT")
        self.assertEqual(revenue.balance, Decimal("20000"))

        self.assertEqual(services.release_due(), 0)  # hold not over yet
        self.assertEqual(services.release_due(now=timezone.now() + timedelta(days=3, minutes=1)), 1)
        self.assertEqual(services.release_due(now=timezone.now() + timedelta(days=4)), 0)  # once
        self.assertEqual(bal(self.tenant), Decimal("180000"))
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_PENDING), 0)
        self.assertHealthy()

    def test_cash_order_commission_is_owed(self):
        row = self.finish(self.order(PaymentMethod.CASH))
        self.assertEqual((row.via_wallet, row.status), (False, "charged"))
        self.assertEqual(bal(self.tenant), Decimal("-20000"))
        self.assertEqual(services.balances(self.tenant)[0]["owed"], "20000")
        # A later wallet order nets the debt.
        fund(self.customer, "500000")
        self.finish(self.order())
        services.release_due(now=timezone.now() + timedelta(days=4))
        self.assertEqual(bal(self.tenant), Decimal("160000"))
        self.assertHealthy()

    def test_once_per_order_and_terms_snapshot(self):
        fund(self.customer, "500000")
        order = self.order()
        for status in [OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY]:
            self.bll.update_order_status(user=self.owner, public_id=order.id, new_status=status)
        self.assertFalse(OrderSettlement.objects.exists())  # not done yet
        self.bll.update_order_status(user=self.owner, public_id=order.id, new_status=OrderStatus.PICKED_UP)
        services.set_terms(self.tenant, data={"commissionPercent": "50"}, actor=self.root)
        services.on_order_done(order.__class__.objects.get(id=order.id))
        self.assertEqual(OrderSettlement.objects.get().commission, Decimal("20000"))  # rate at completion time

    def test_tenant_override_and_zero_hold(self):
        services.set_terms(self.tenant, data={"commissionPercent": "2.5", "holdDays": 0}, actor=self.root)
        fund(self.customer, "500000")
        row = self.finish(self.order())
        self.assertEqual((row.commission, row.status), (Decimal("5000"), "released"))
        self.assertEqual(bal(self.tenant), Decimal("195000"))
        terms = services.terms_for(self.tenant)
        self.assertTrue(terms["commissionIsCustom"] and terms["holdIsCustom"])
        services.set_terms(self.tenant, data={"commissionPercent": "", "holdDays": ""}, actor=self.root)
        self.assertEqual(services.terms_for(self.tenant)["commissionPercent"], "10")
        self.assertHealthy()

    def test_cancelled_before_done_refunds_everything(self):
        fund(self.customer, "500000")
        order = self.order()
        self.bll.update_order_status(user=self.owner, public_id=order.id, new_status=OrderStatus.CANCELLED)
        self.assertEqual(wallet.balance_of(self.customer, "IRT"), Decimal("500000"))
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_PENDING), 0)
        self.assertFalse(OrderSettlement.objects.exists())
        self.assertHealthy()


class PayoutTests(Base):
    def setUp(self):
        super().setUp()
        services.set_terms(self.tenant, data={"holdDays": 0}, actor=self.root)
        fund(self.customer, "1000000")
        for _ in range(2):
            self.finish(self.order())  # 2 x 180,000 available
        self.owner_api = self.client_for(self.owner)
        self.root_api = self.client_for(self.root)
        self.base = f"/api/settlement/tenants/{self.tenant.id}"

    def approved_iban(self):
        res = self.owner_api.post(f"{self.base}/accounts/", {"kind": "iban", "iban": IBAN, "holderName": "Sara"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.root_api.post(f"/api/settlement/admin/accounts/{res.data['id']}/approve/")
        return res.data["id"]

    def test_full_payout_flow(self):
        account = self.approved_iban()
        self.assertTrue(PayoutAccount.objects.get(id=account).is_default)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.owner_api.post(f"{self.base}/payouts/", {"accountId": account, "amount": "300000"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(bal(self.tenant), Decimal("60000"))
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_RESERVED), Decimal("300000"))
        self.assertTrue(Notification.objects.filter(recipient=self.root, type="settlement_payout_requested").exists())

        pid = res.data["id"]
        self.assertEqual(self.root_api.post(f"/api/settlement/admin/payouts/{pid}/paid/", {}).status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.root_api.post(f"/api/settlement/admin/payouts/{pid}/paid/", {"reference": "TRK-12345"})
        self.assertEqual(res.data["status"], "paid")
        self.assertEqual(self.root_api.post(f"/api/settlement/admin/payouts/{pid}/paid/", {"reference": "x"}).status_code, 400)
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_RESERVED), 0)
        self.assertEqual(WalletAccount.objects.get(kind=AccountKind.SYSTEM_PAYOUT, currency="IRT").balance, Decimal("300000"))
        self.assertTrue(Notification.objects.filter(recipient=self.owner, type="settlement_payout_paid").exists())
        self.assertHealthy()

    def test_rules(self):
        res = self.owner_api.post(f"{self.base}/accounts/", {"kind": "iban", "iban": IBAN, "holderName": "Sara"}, format="json")
        pending = res.data["id"]
        # Not approved yet.
        self.assertEqual(self.owner_api.post(f"{self.base}/payouts/", {"accountId": pending, "amount": "100000"}).status_code, 400)
        self.root_api.post(f"/api/settlement/admin/accounts/{pending}/approve/")
        self.assertEqual(self.owner_api.post(f"{self.base}/payouts/", {"accountId": pending, "amount": "10000"}).status_code, 400)  # minimum
        self.assertEqual(self.owner_api.post(f"{self.base}/payouts/", {"accountId": pending, "amount": "999999"}).status_code, 400)  # balance
        # Bad IBAN checksum / bad address.
        self.assertEqual(self.owner_api.post(f"{self.base}/accounts/", {"kind": "iban", "iban": IBAN[:-1] + "3", "holderName": "x"}).status_code, 400)
        self.assertEqual(self.owner_api.post(f"{self.base}/accounts/", {"kind": "crypto", "asset": "USDT_TRC20", "address": "0x12"}).status_code, 400)
        self.assertEqual(self.owner_api.post(f"{self.base}/accounts/", {"kind": "crypto", "asset": "USDT_TRC20", "address": TRC20}).data["currency"], "USDT")

    def test_cancel_and_reject_return_the_money(self):
        account = self.approved_iban()
        a = self.owner_api.post(f"{self.base}/payouts/", {"accountId": account, "amount": "100000"}).data["id"]
        b = self.owner_api.post(f"{self.base}/payouts/", {"accountId": account, "amount": "100000"}).data["id"]
        self.assertEqual(self.owner_api.post(f"{self.base}/payouts/{a}/cancel/").data["status"], "cancelled")
        self.assertEqual(self.root_api.post(f"/api/settlement/admin/payouts/{b}/reject/", {}).status_code, 400)
        self.assertEqual(self.root_api.post(f"/api/settlement/admin/payouts/{b}/reject/", {"reason": "wrong holder"}).data["status"], "rejected")
        self.assertEqual(self.owner_api.post(f"{self.base}/payouts/{b}/cancel/").status_code, 400)
        self.assertEqual(bal(self.tenant), Decimal("360000"))
        self.assertEqual(bal(self.tenant, AccountKind.BUSINESS_RESERVED), 0)
        self.assertHealthy()

    def test_only_owner_or_superuser(self):
        stranger = self.client_for(make_user())
        self.assertEqual(stranger.get(f"{self.base}/overview/").status_code, 403)
        self.assertEqual(stranger.post(f"{self.base}/accounts/", {"kind": "iban", "iban": IBAN, "holderName": "x"}).status_code, 403)
        self.assertEqual(self.owner_api.get("/api/settlement/admin/payouts/").status_code, 403)
        self.assertEqual(self.owner_api.put("/api/settlement/admin/settings/", {}, format="json").status_code, 403)
        self.assertEqual(self.root_api.get(f"{self.base}/overview/").status_code, 200)

    def test_overview_statement_and_csv(self):
        data = self.owner_api.get(f"{self.base}/overview/").data
        self.assertEqual(data["balances"][0]["available"], "360000")
        self.assertEqual(data["terms"]["commissionPercent"], "10")
        lines = self.owner_api.get(f"{self.base}/statement/", {"currency": "IRT"}).data
        kinds = {line["kind"] for line in lines["results"]}
        self.assertTrue({"order_payment", "commission", "release"} <= kinds)
        csv_res = self.owner_api.get(f"{self.base}/statement.csv")
        self.assertEqual(csv_res["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("commission", csv_res.content.decode())
        orders = self.owner_api.get(f"{self.base}/orders/").data
        self.assertEqual(orders["count"], 2)

    def test_auto_payout_is_off_until_enabled(self):
        self.approved_iban()
        saturday = timezone.now()
        while saturday.weekday() != 5:
            saturday += timedelta(days=1)
        self.assertEqual(services.run_auto_payouts(now=saturday), 0)
        res = self.root_api.put("/api/settlement/admin/settings/", {"auto_payout": {"enabled": True, "weekday": 5}}, format="json")
        self.assertTrue(res.data["auto_payout"]["enabled"])
        self.assertEqual(services.run_auto_payouts(now=saturday - timedelta(days=1)), 0)  # wrong day
        self.assertEqual(services.run_auto_payouts(now=saturday), 1)
        self.assertEqual(services.run_auto_payouts(now=saturday), 0)  # once a week
        payout = Payout.objects.get()
        self.assertTrue(payout.automatic)
        self.assertEqual(payout.amount, Decimal("360000"))
        self.assertHealthy()


class PlatformTests(Base):
    def test_settings_and_terms_validation(self):
        api = self.client_for(self.root)
        self.assertEqual(api.put("/api/settlement/admin/settings/", {"commission_percent": "80"}, format="json").status_code, 400)
        self.assertEqual(api.put("/api/settlement/admin/settings/", {"hold_days": -1}, format="json").status_code, 400)
        ok = api.put("/api/settlement/admin/settings/", {"commission_percent": "7.5", "hold_days": 5}, format="json")
        self.assertEqual((ok.data["commission_percent"], ok.data["hold_days"]), ("7.50", 5))
        self.assertFalse(ok.data["auto_payout"]["enabled"])
        url = f"/api/settlement/admin/tenants/{self.tenant.id}/terms/"
        self.assertEqual(api.put(url, {"commissionPercent": "abc"}, format="json").status_code, 400)
        self.assertEqual(api.put(url, {"commissionPercent": "3", "note": "launch deal"}, format="json").data["commissionPercent"], "3")
        tenants = api.get("/api/settlement/admin/tenants/", {"search": self.tenant.name[:6]}).data
        self.assertEqual(tenants["results"][0]["terms"]["commissionPercent"], "3")
        overview = api.get("/api/settlement/admin/overview/").data
        self.assertIn("openPayouts", overview)

    def test_iban_checksum(self):
        self.assertTrue(services.valid_iban(IBAN))
        self.assertFalse(services.valid_iban("IR000000000000000000000000"))
