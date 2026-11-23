"""Wallet top-ups: gateways are mocked at the HTTP layer; what matters is that
money is credited only after server-side confirmation, and only once."""
import json
import os
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from orders.tests.test_console_websocket import make_user
from platform_settings.models import PlatformSetting
from wallet import services, topups
from wallet.gateways.crypto import NOWPayments, cryptomus_sign
from wallet.gateways.sandbox import sandbox_token
from wallet.models import LedgerTransaction, TopUp

TRC20 = "TJYeasTPa6gpEEfYqfq6PJG6M1rMhEkSvR"
TON_ADDR = "UQ" + "A" * 46

ENV = {
    "ZARINPAL_MERCHANT_ID": "zp-merchant",
    "IDPAY_API_KEY": "idpay-key",
    "MELLAT_TERMINAL_ID": "1",
    "MELLAT_USERNAME": "u",
    "MELLAT_PASSWORD": "p",
    "SADAD_MERCHANT_ID": "m",
    "SADAD_TERMINAL_ID": "t",
    "SADAD_TERMINAL_KEY": "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0",
    "NOWPAYMENTS_API_KEY": "np-key",
    "NOWPAYMENTS_IPN_SECRET": "np-secret",
    "CRYPTOMUS_MERCHANT_ID": "cm",
    "CRYPTOMUS_PAYMENT_KEY": "cm-key",
}


def enable(**overrides):
    value = {
        "bank": {"providers": ["zarinpal", "idpay", "mellat", "sadad"], "min": "1000", "max": "50000000"},
        "crypto": {
            "providers": ["nowpayments", "cryptomus", "direct"],
            "coins": {
                "USDT_TRC20": {"enabled": True, "min": "5", "max": "1000", "address": TRC20},
                "USDT_BEP20": {"enabled": True, "min": "5", "max": "1000", "address": ""},
                "TON": {"enabled": True, "min": "1", "max": "1000", "address": TON_ADDR},
                "XRP": {"enabled": False, "min": "1", "max": "1000", "address": ""},
            },
        },
        "expire_minutes": 60,
    }
    value.update(overrides)
    PlatformSetting.objects.update_or_create(key=topups.SETTINGS_KEY, defaults={"value": value})


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        enable()
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def start(self, **body):
        return self.client.post("/api/wallet/topups/", body, format="json")


class ZarinpalTests(Base):
    def _start(self):
        with mock.patch("wallet.gateways.bank.http_json", return_value={"data": {"code": 100, "authority": "A0001"}}) as req:
            res = self.start(method="bank", provider="zarinpal", amount="50000")
        self.assertEqual(res.status_code, 201, res.content)
        sent = req.call_args.kwargs["body"]
        self.assertEqual(sent["amount"], 500000)  # rials
        self.assertTrue(sent["callback_url"].endswith(f"/api/wallet/topups/{res.data['topup']['id']}/callback/"))
        self.assertEqual(res.data["redirect"]["url"], "https://payment.zarinpal.com/pg/StartPay/A0001")
        return res.data["topup"]["id"]

    def test_paid_once_after_verify(self):
        topup_id = self._start()
        self.assertEqual(services.balance_of(self.user, "IRT"), 0)  # nothing before verify
        anon = APIClient()
        verify = {"data": {"code": 100, "ref_id": 777, "card_pan": "6037****1111"}}
        with mock.patch("wallet.gateways.bank.http_json", return_value=verify) as v, self.captureOnCommitCallbacks(execute=True):
            res = anon.get(f"/api/wallet/topups/{topup_id}/callback/", {"Authority": "A0001", "Status": "OK"})
            anon.get(f"/api/wallet/topups/{topup_id}/callback/", {"Authority": "A0001", "Status": "OK"})
        self.assertEqual(res.status_code, 302)
        self.assertIn(f"/dashboard/wallet?topup={topup_id}", res["Location"])
        self.assertEqual(v.call_count, 1)  # second return sees it is already paid
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("50000"))
        topup = TopUp.objects.get(id=topup_id)
        self.assertEqual((topup.status, topup.receipt_ref), ("paid", "777"))
        self.assertEqual(LedgerTransaction.objects.filter(kind="topup").count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.user, type="wallet_topup").exists())
        self.assertTrue(services.health()["ok"])

    def test_cancelled_at_gateway(self):
        topup_id = self._start()
        with mock.patch("wallet.gateways.bank.http_json") as v:
            APIClient().get(f"/api/wallet/topups/{topup_id}/callback/", {"Authority": "A0001", "Status": "NOK"})
        v.assert_not_called()
        self.assertEqual(TopUp.objects.get(id=topup_id).status, "cancelled")
        self.assertEqual(services.balance_of(self.user, "IRT"), 0)

    def test_failed_verify_and_forged_authority(self):
        topup_id = self._start()
        with mock.patch("wallet.gateways.bank.http_json", return_value={"data": {"code": 100}}) as v:
            APIClient().get(f"/api/wallet/topups/{topup_id}/callback/", {"Authority": "OTHER", "Status": "OK"})
        v.assert_not_called()
        self.assertEqual(TopUp.objects.get(id=topup_id).status, "failed")
        self.assertEqual(services.balance_of(self.user, "IRT"), 0)

    def test_unreachable_gateway_stays_pending(self):
        topup_id = self._start()
        from wallet.gateways import GatewayError

        with mock.patch("wallet.gateways.bank.http_json", side_effect=GatewayError("down")):
            APIClient().get(f"/api/wallet/topups/{topup_id}/callback/", {"Authority": "A0001", "Status": "OK"})
        self.assertEqual(TopUp.objects.get(id=topup_id).status, "pending")

    def test_refused_request_is_failed(self):
        with mock.patch("wallet.gateways.bank.http_json", return_value={"errors": {"code": -9, "message": "bad"}}):
            res = self.start(method="bank", provider="zarinpal", amount="50000")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(TopUp.objects.get().status, "failed")


class OtherBankTests(Base):
    def test_idpay(self):
        with mock.patch("wallet.gateways.bank.http_json", return_value={"id": "ID1", "link": "https://idpay.ir/p/ws/ID1"}):
            res = self.start(method="bank", provider="idpay", amount="20000")
        topup = TopUp.objects.get(id=res.data["topup"]["id"])
        reply = {"status": 100, "amount": 200000, "track_id": "T9", "payment": {"card_no": "6219****"}}
        with mock.patch("wallet.gateways.bank.http_json", return_value=reply):
            APIClient().post(
                f"/api/wallet/topups/{topup.id}/callback/",
                {"status": "10", "id": "ID1", "order_id": str(topup.order_number)},
            )
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("20000"))

    def test_mellat_verify_settle_and_reversal(self):
        with mock.patch("wallet.gateways.bank.http_raw", return_value="<return>0,REF1</return>"):
            res = self.start(method="bank", provider="mellat", amount="10000")
        self.assertEqual(res.data["redirect"]["method"], "POST")
        self.assertEqual(res.data["redirect"]["fields"]["RefId"], "REF1")
        topup = TopUp.objects.get(id=res.data["topup"]["id"])
        cb = {"RefId": "REF1", "ResCode": "0", "SaleOrderId": str(topup.order_number), "SaleReferenceId": "555"}
        with mock.patch("wallet.gateways.bank.http_raw", side_effect=["<return>0</return>", "<return>0</return>"]) as raw:
            APIClient().post(f"/api/wallet/topups/{topup.id}/callback/", cb)
        self.assertIn("bpVerifyRequest", raw.call_args_list[0].kwargs["body"].decode())
        self.assertIn("bpSettleRequest", raw.call_args_list[1].kwargs["body"].decode())
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("10000"))

        with mock.patch("wallet.gateways.bank.http_raw", return_value="<return>0,REF2</return>"):
            res = self.start(method="bank", provider="mellat", amount="10000")
        topup = TopUp.objects.get(id=res.data["topup"]["id"])
        cb = {"RefId": "REF2", "ResCode": "0", "SaleOrderId": str(topup.order_number), "SaleReferenceId": "556"}
        with mock.patch("wallet.gateways.bank.http_raw", side_effect=["<return>415</return>", "<return>0</return>"]) as raw:
            APIClient().post(f"/api/wallet/topups/{topup.id}/callback/", cb)
        self.assertIn("bpReversalRequest", raw.call_args_list[1].kwargs["body"].decode())
        self.assertEqual(TopUp.objects.get(id=topup.id).status, "failed")
        self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("10000"))

    def test_sadad_amount_mismatch_is_not_credited(self):
        with mock.patch("wallet.gateways.bank.http_json", return_value={"ResCode": 0, "Token": "TOK"}) as req:
            res = self.start(method="bank", provider="sadad", amount="10000")
        self.assertTrue(req.call_args.kwargs["body"]["SignData"])
        topup = TopUp.objects.get(id=res.data["topup"]["id"])
        with mock.patch("wallet.gateways.bank.http_json", return_value={"ResCode": 0, "Amount": 1000, "RetrivalRefNo": "R"}):
            APIClient().post(
                f"/api/wallet/topups/{topup.id}/callback/", {"Token": "TOK", "ResCode": "0", "OrderId": str(topup.order_number)}
            )
        self.assertEqual(TopUp.objects.get(id=topup.id).status, "failed")
        self.assertEqual(services.balance_of(self.user, "IRT"), 0)


class CryptoTests(Base):
    def _np_start(self, amount="20"):
        reply = {"id": 4521, "invoice_url": "https://nowpayments.io/payment/?iid=4521"}
        with mock.patch("wallet.gateways.crypto.http_json", return_value=reply) as req:
            res = self.start(method="crypto", provider="nowpayments", asset="USDT_TRC20", amount=amount)
        self.assertEqual(res.status_code, 201, res.content)
        body = req.call_args.kwargs["body"]
        self.assertEqual(body["pay_currency"], "usdttrc20")
        self.assertTrue(body["ipn_callback_url"].endswith("/api/wallet/topups/webhook/nowpayments/"))
        return res.data["topup"]["id"]

    def _np_webhook(self, payload, secret="np-secret"):
        sig = NOWPayments.signature(payload, secret)
        return APIClient().post(
            "/api/wallet/topups/webhook/nowpayments/", data=json.dumps(payload), content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG=sig,
        )

    def test_nowpayments_signed_finished_credits_usdt_once(self):
        topup_id = self._np_start()
        payload = {"invoice_id": 4521, "payment_id": 99, "payment_status": "finished", "actually_paid": 20, "pay_currency": "usdttrc20"}
        self.assertEqual(self._np_webhook(payload, secret="wrong").status_code, 400)
        self.assertEqual(services.balance_of(self.user, "USDT"), 0)
        self.assertEqual(self._np_webhook({**payload, "payment_status": "confirming"}).status_code, 200)
        self.assertEqual(TopUp.objects.get(id=topup_id).status, "pending")
        self._np_webhook(payload)
        self._np_webhook(payload)
        self.assertEqual(services.balance_of(self.user, "USDT"), Decimal("20"))
        self.assertEqual(services.balance_of(self.user, "IRT"), 0)

    def test_underpaid_credits_what_arrived(self):
        topup_id = self._np_start("20")
        self._np_webhook({"invoice_id": 4521, "payment_id": 1, "payment_status": "finished", "actually_paid": "12.5"})
        self.assertEqual(services.balance_of(self.user, "USDT"), Decimal("12.5"))
        self.assertEqual(TopUp.objects.get(id=topup_id).credited_amount, Decimal("12.5"))

    def test_cryptomus(self):
        reply = {"state": 0, "result": {"uuid": "c-uuid", "url": "https://pay.cryptomus.com/pay/c-uuid"}}
        with mock.patch("wallet.gateways.crypto.http_json", return_value=reply) as req:
            res = self.start(method="crypto", provider="cryptomus", asset="TON", amount="3")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(req.call_args.kwargs["body"]["network"], "ton")
        payload = {"uuid": "c-uuid", "status": "paid", "payment_amount": "3", "txid": "abc/def"}
        signed = {**payload, "sign": cryptomus_sign(payload, "cm-key")}
        forged = {**payload, "sign": "0" * 32}
        url = "/api/wallet/topups/webhook/cryptomus/"
        self.assertEqual(APIClient().post(url, data=json.dumps(forged), content_type="application/json").status_code, 400)
        self.assertEqual(APIClient().post(url, data=json.dumps(signed), content_type="application/json").status_code, 200)
        self.assertEqual(services.balance_of(self.user, "TON"), Decimal("3"))

    def test_direct_transfer_review(self):
        res = self.start(method="crypto", provider="direct", asset="TON", amount="2")
        self.assertEqual(res.status_code, 201, res.content)
        ins = res.data["instructions"]
        self.assertEqual(ins["address"], TON_ADDR)
        self.assertEqual(ins["memo"], str(res.data["topup"]["orderNumber"]))
        topup_id = res.data["topup"]["id"]
        self.assertEqual(self.client.post(f"/api/wallet/topups/{topup_id}/tx/", {"txHash": "x"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/wallet/topups/{topup_id}/tx/", {"txHash": "a" * 64}).status_code, 200)

        # Customers cannot approve their own.
        self.assertEqual(self.client.post(f"/api/wallet/admin/topups/{topup_id}/approve/", {}).status_code, 403)
        root = APIClient()
        root.force_authenticate(make_user(is_superuser=True, is_staff=True))
        review = root.get("/api/wallet/admin/topups/", {"status": "review"}).data
        self.assertEqual([r["id"] for r in review["results"]], [topup_id])
        self.assertEqual(root.post(f"/api/wallet/admin/topups/{topup_id}/approve/", {"amount": "5"}).status_code, 400)
        res = root.post(f"/api/wallet/admin/topups/{topup_id}/approve/", {"note": "seen on tonviewer"})
        self.assertEqual(res.data["status"], "paid")
        root.post(f"/api/wallet/admin/topups/{topup_id}/approve/", {})
        self.assertEqual(services.balance_of(self.user, "TON"), Decimal("2"))

    def test_direct_needs_an_address(self):
        res = self.start(method="crypto", provider="direct", asset="USDT_BEP20", amount="10")
        self.assertEqual(res.status_code, 400)
        coins = {c["key"]: c for c in self.client.get("/api/wallet/topups/options/").data["crypto"]}
        self.assertNotIn("direct", coins["USDT_BEP20"]["providers"])
        self.assertNotIn("XRP", coins)  # disabled

    def test_reject(self):
        topup_id = self.start(method="crypto", provider="direct", asset="USDT_TRC20", amount="10").data["topup"]["id"]
        root = APIClient()
        root.force_authenticate(make_user(is_superuser=True, is_staff=True))
        self.assertEqual(root.post(f"/api/wallet/admin/topups/{topup_id}/reject/", {}).status_code, 400)
        self.assertEqual(root.post(f"/api/wallet/admin/topups/{topup_id}/reject/", {"reason": "no tx"}).data["status"], "failed")
        self.assertEqual(services.balance_of(self.user, "USDT"), 0)


class RulesTests(Base):
    def test_unconfigured_or_disabled_gateways_are_hidden(self):
        with mock.patch.dict(os.environ, {"ZARINPAL_MERCHANT_ID": ""}):
            opts = self.client.get("/api/wallet/topups/options/").data
            self.assertNotIn("zarinpal", opts["bank"]["providers"])
            self.assertEqual(self.start(method="bank", provider="zarinpal", amount="50000").status_code, 400)
        self.assertNotIn("test", opts["bank"]["providers"])

    def test_amount_bounds_and_daily_limit_before_paying(self):
        self.assertEqual(self.start(method="bank", provider="zarinpal", amount="10").status_code, 400)
        PlatformSetting.objects.create(key=services.LIMITS_KEY, value={"daily_topup": {"IRT": "30000"}})
        with mock.patch("wallet.gateways.bank.http_json") as req:
            res = self.start(method="bank", provider="zarinpal", amount="50000")
        self.assertEqual(res.status_code, 400)
        req.assert_not_called()

    def test_settings_validation(self):
        root = APIClient()
        root.force_authenticate(make_user(is_superuser=True, is_staff=True))
        bad = {"crypto": {"coins": {"USDT_TRC20": {"address": "0x123"}}}}
        self.assertEqual(root.put("/api/wallet/admin/topup-settings/", bad, format="json").status_code, 400)
        self.assertEqual(root.put("/api/wallet/admin/topup-settings/", {"bank": {"providers": ["paypal"]}}, format="json").status_code, 400)
        ok = root.put("/api/wallet/admin/topup-settings/", {"bank": {"providers": ["zarinpal"], "min": "5000"}}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data["bank"]["providers"], ["zarinpal"])
        self.assertTrue(ok.data["configured"]["zarinpal"])
        self.assertEqual(ok.data["crypto"]["coins"]["TON"]["address"], TON_ADDR)  # untouched
        self.assertEqual(self.client.get("/api/wallet/admin/topup-settings/").status_code, 403)

    def test_sandbox_gateway_token(self):
        with mock.patch.dict(os.environ, {"WALLET_TEST_GATEWAY": "1"}):
            res = self.start(method="bank", provider="test", amount="5000")
            self.assertEqual(res.status_code, 201, res.content)
            topup_id = res.data["topup"]["id"]
            self.assertTrue(res.data["redirect"]["url"].endswith("/dashboard/wallet/topup-test"))
            APIClient().get(f"/api/wallet/topups/{topup_id}/callback/", {"outcome": "ok", "token": "forged"})
            self.assertEqual(TopUp.objects.get(id=topup_id).status, "failed")

            topup_id = self.start(method="bank", provider="test", amount="5000").data["topup"]["id"]
            APIClient().get(f"/api/wallet/topups/{topup_id}/callback/", {"outcome": "ok", "token": sandbox_token(topup_id, "ok")})
            self.assertEqual(services.balance_of(self.user, "IRT"), Decimal("5000"))

            res = self.start(method="crypto", provider="test", asset="XRP", amount="4")  # coin disabled, sandbox still works
            self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.start(method="bank", provider="test", amount="5000").status_code, 400)

    def test_expire_and_cancel(self):
        with mock.patch("wallet.gateways.bank.http_json", return_value={"data": {"code": 100, "authority": "A1"}}):
            old = self.start(method="bank", provider="zarinpal", amount="50000").data["topup"]["id"]
            fresh = self.start(method="bank", provider="zarinpal", amount="50000").data["topup"]["id"]
        TopUp.objects.filter(id=old).update(created_at=timezone.now() - timezone.timedelta(hours=2))
        self.assertEqual(topups.expire_stale(), 1)
        self.assertEqual(TopUp.objects.get(id=old).status, "expired")
        self.assertEqual(self.client.post(f"/api/wallet/topups/{fresh}/cancel/").data["status"], "cancelled")
        other = APIClient()
        other.force_authenticate(make_user())
        self.assertEqual(other.get(f"/api/wallet/topups/{fresh}/").status_code, 404)
