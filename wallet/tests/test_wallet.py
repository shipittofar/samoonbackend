from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from menu.models import MenuCategory, MenuItem
from notifications.models import Notification
from orders.models import Order, OrderStatus, OrderType, PaymentMethod, PaymentStatus
from orders.services.orders_bll import OrdersBusinessLogicLayer
from orders.tests.test_console_websocket import make_branch, make_tenant_with_owner, make_user
from platform_settings.models import PlatformSetting
from wallet import services
from wallet.models import AccountKind, LedgerEntry, LedgerTransaction, WalletAccount


def fund(user, amount, currency="IRT", key=None):
    root = make_user(is_superuser=True)
    return services.adjust(
        user=user, currency=currency, amount=amount, reason="test funding", actor=root,
        idempotency_key=key or f"fund-{user.id}-{amount}",
    )


class LedgerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def test_adjust_is_balanced_and_idempotent(self):
        tx1 = fund(self.user, "500000", key="same")
        tx2 = fund(self.user, "500000", key="same")
        self.assertEqual(tx1.id, tx2.id)
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("500000"))
        self.assertEqual(sum(e.amount for e in tx1.entries.all()), 0)
        self.assertTrue(services.health()["ok"])

    def test_customer_wallet_never_goes_negative(self):
        fund(self.user, "100")
        with self.assertRaises(services.InsufficientFunds):
            fund(self.user, "-150", key="debit")
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("100"))
        self.assertEqual(LedgerTransaction.objects.count(), 1)  # the failed one left nothing

    def test_adjust_needs_a_reason_and_nonzero_amount(self):
        from rest_framework.exceptions import ValidationError

        root = make_user(is_superuser=True)
        with self.assertRaises(ValidationError):
            services.adjust(user=self.user, currency="IRT", amount="10", reason=" ", actor=root, idempotency_key="k1")
        with self.assertRaises(ValidationError):
            services.adjust(user=self.user, currency="IRT", amount="0", reason="x", actor=root, idempotency_key="k2")

    def test_unbalanced_post_is_refused(self):
        account = services.customer_account(self.user, "IRT")
        with self.assertRaises(ValueError):
            services.post(kind="adjustment", currency="IRT", legs=[services.Leg(account, Decimal("5"))], idempotency_key="bad")

    def test_health_detects_a_tampered_balance(self):
        fund(self.user, "1000")
        WalletAccount.objects.filter(kind=AccountKind.CUSTOMER, user=self.user).update(balance=Decimal("999999"))
        report = services.health()
        self.assertFalse(report["ok"])
        self.assertTrue(any("balance" in p for p in report["problems"]))

    def test_frozen_wallet_cannot_spend(self):
        fund(self.user, "1000")
        WalletAccount.objects.filter(kind=AccountKind.CUSTOMER, user=self.user).update(is_frozen=True)
        with self.assertRaises(services.WalletFrozen):
            fund(self.user, "-10", key="spend")


class OrderPaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant, currency="IRT", ordering_enabled=True, wallet_payment_enabled=True)
        cat = MenuCategory.objects.create(branch=self.branch, name="Coffee")
        self.item = MenuItem.objects.create(branch=self.branch, category=cat, name="Espresso", price=Decimal("200000"))
        self.customer = make_user()
        self.bll = OrdersBusinessLogicLayer()

    def order(self, qty=1):
        return self.bll.create_order(
            customer=self.customer,
            validated_data={
                "branch_id": self.branch.id,
                "order_type": OrderType.PICKUP,
                "payment_method": PaymentMethod.WALLET,
                "items": [{"menu_item_id": self.item.id, "quantity": qty}],
            },
        )

    def test_not_enough_balance_means_no_order(self):
        fund(self.customer, "100000")
        with self.assertRaises(services.InsufficientFunds):
            self.order()
        self.assertFalse(Order.objects.exists())
        self.assertEqual(services.balance_of(self.customer, "IRT"), Decimal("100000"))

    def test_paying_moves_money_to_the_business(self):
        fund(self.customer, "500000")
        with self.captureOnCommitCallbacks(execute=True):
            order = self.order()
        self.assertEqual(order.payment_status, PaymentStatus.PAID)
        self.assertEqual(services.balance_of(self.customer, "IRT"), Decimal("300000"))
        business = WalletAccount.objects.get(kind=AccountKind.BUSINESS_PENDING, tenant=self.tenant, currency="IRT")  # held until settled
        self.assertEqual(business.balance, Decimal("200000"))
        self.assertTrue(services.health()["ok"])
        self.assertTrue(Notification.objects.filter(recipient=self.customer, type="wallet_payment").exists())

    def test_cancellation_refunds_once(self):
        fund(self.customer, "500000")
        order = self.order()
        with self.captureOnCommitCallbacks(execute=True):
            self.bll.cancel_order(customer=self.customer, public_id=order.id)
        self.bll.cancel_order(customer=self.customer, public_id=order.id)  # second call: no second refund
        self.assertEqual(services.balance_of(self.customer, "IRT"), Decimal("500000"))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, PaymentStatus.REFUNDED)
        self.assertEqual(LedgerTransaction.objects.filter(order=order, kind="order_refund").count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.customer, type="wallet_refund").exists())
        self.assertTrue(services.health()["ok"])

    def test_owner_cancelling_refunds_too(self):
        fund(self.customer, "500000")
        order = self.order()
        self.bll.update_order_status(user=self.owner, public_id=order.id, new_status=OrderStatus.CANCELLED)
        self.assertEqual(services.balance_of(self.customer, "IRT"), Decimal("500000"))

    def test_per_transaction_limit(self):
        PlatformSetting.objects.create(key=services.LIMITS_KEY, value={"per_transaction": {"IRT": "150000"}})
        fund(self.customer, "500000")
        with self.assertRaises(services.LimitExceeded):
            self.order()
        self.assertFalse(Order.objects.exists())

    def test_cash_orders_do_not_touch_the_wallet(self):
        self.branch.cash_payment_enabled = True
        self.branch.save()
        self.bll.create_order(
            customer=self.customer,
            validated_data={
                "branch_id": self.branch.id, "order_type": OrderType.PICKUP, "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": self.item.id, "quantity": 1}],
            },
        )
        self.assertFalse(LedgerTransaction.objects.exists())


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.other = make_user()
        fund(self.user, "250000")
        fund(self.other, "1")
        self.root = make_user(is_superuser=True, is_staff=True)

    def test_own_wallet_and_lines_only(self):
        c = APIClient()
        c.force_authenticate(self.user)
        self.assertEqual(c.get("/api/wallet/").json()["accounts"], [{"currency": "IRT", "balance": "250000", "frozen": False}])
        lines = c.get("/api/wallet/transactions/").json()
        self.assertEqual(lines["count"], 1)
        self.assertEqual(lines["results"][0]["amount"], "250000")
        self.assertEqual(APIClient().get("/api/wallet/").status_code, 401)

    def test_superuser_adjust_with_key_and_others_refused(self):
        c = APIClient()
        c.force_authenticate(self.root)
        url = f"/api/wallet/admin/users/{self.user.id}/adjust/"
        self.assertEqual(c.post(url, {"currency": "IRT", "amount": "1000", "reason": "x"}, format="json").status_code, 400)
        body = {"currency": "IRT", "amount": "-50000", "reason": "Wrong charge", "idempotencyKey": "adj-0001"}
        self.assertEqual(c.post(url, body, format="json").status_code, 200)
        self.assertEqual(c.post(url, body, format="json").status_code, 200)  # same key: once
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("200000"))
        self.assertEqual(c.get("/api/wallet/admin/health/").json()["ok"], True)
        self.assertEqual(c.get("/api/wallet/admin/users/", {"search": self.user.phone_number[-6:]}).status_code, 200)
        owner, _ = make_tenant_with_owner()
        c.force_authenticate(owner)
        self.assertEqual(c.post(url, body | {"idempotencyKey": "adj-0002"}, format="json").status_code, 403)
        self.assertEqual(c.get("/api/wallet/admin/health/").status_code, 403)

    def test_limits_settings(self):
        c = APIClient()
        c.force_authenticate(self.root)
        res = c.put("/api/wallet/admin/limits/", {"per_transaction": {"irt": "5000000"}, "daily_spend": {}}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(services.limits()["per_transaction"], {"IRT": "5000000"})
        self.assertEqual(c.put("/api/wallet/admin/limits/", {"per_transaction": {"IRT": "-1"}}, format="json").status_code, 400)

    def test_ledger_is_append_only_in_admin(self):
        from django.contrib import admin

        for model in (WalletAccount, LedgerTransaction):  # entries are only an inline
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))
