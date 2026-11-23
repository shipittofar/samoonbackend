"""Crypto top-ups: USDT (TRC20 / BEP20), TON and XRP.

The wallet is credited in the coin itself (USDT, TON or XRP balance), never
converted. Three ways in:

* ``nowpayments`` and ``cryptomus``: hosted invoice; we credit only on a
  signed webhook that says the payment is final.
* ``direct``: the payer sends to a receiving address the platform registered
  in the panel (with the top-up number as memo / destination tag), then
  submits the transaction hash; a superuser checks it on-chain and approves.

Environment (server .env):
  NOWPAYMENTS_API_KEY, NOWPAYMENTS_IPN_SECRET, NOWPAYMENTS_SANDBOX=1
  CRYPTOMUS_MERCHANT_ID, CRYPTOMUS_PAYMENT_KEY
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from wallet.gateways.base import Gateway, GatewayError, Redirect, Verdict, env, env_flag, http_json


@dataclass(frozen=True)
class Coin:
    key: str  # our asset key
    currency: str  # wallet currency credited
    network: str  # human label
    nowpayments: str  # NOWPayments pay_currency
    cryptomus_currency: str
    cryptomus_network: str
    needs_memo: bool  # TON / XRP deposits to a shared address need a memo / tag


COINS: dict[str, Coin] = {
    "USDT_TRC20": Coin("USDT_TRC20", "USDT", "TRC20 (Tron)", "usdttrc20", "USDT", "tron", False),
    "USDT_BEP20": Coin("USDT_BEP20", "USDT", "BEP20 (BNB Chain)", "usdtbsc", "USDT", "bsc", False),
    "TON": Coin("TON", "TON", "TON", "ton", "TON", "ton", True),
    "XRP": Coin("XRP", "XRP", "XRP Ledger", "xrp", "XRP", "xrp", True),
}


def coin(key: str) -> Coin:
    try:
        return COINS[key]
    except KeyError:
        raise GatewayError("Unknown coin.")


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


# ── NOWPayments ──────────────────────────────────────────────────────────────


class NOWPayments(Gateway):
    key = "nowpayments"
    method = "crypto"
    currencies = ("USDT", "TON", "XRP")

    @property
    def base(self) -> str:
        return "https://api-sandbox.nowpayments.io/v1" if env_flag("NOWPAYMENTS_SANDBOX") else "https://api.nowpayments.io/v1"

    def configured(self) -> bool:
        return bool(env("NOWPAYMENTS_API_KEY") and env("NOWPAYMENTS_IPN_SECRET"))

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        c = coin(topup.asset)
        reply = http_json("POST", f"{self.base}/invoice", headers={"x-api-key": env("NOWPAYMENTS_API_KEY")}, body={
            "price_amount": float(topup.amount),
            "price_currency": c.nowpayments,
            "pay_currency": c.nowpayments,
            "order_id": str(topup.id),
            "order_description": f"Wallet top-up {topup.order_number}",
            "ipn_callback_url": callback_url,
            "success_url": return_url,
            "cancel_url": return_url,
            "is_fixed_rate": True,
            "is_fee_paid_by_user": True,
        })
        topup.log("nowpayments.invoice", reply)
        if not reply.get("id") or not reply.get("invoice_url"):
            raise GatewayError(f"NOWPayments refused the invoice ({reply.get('message') or reply.get('code') or 'unknown'}).")
        topup.gateway_ref = str(reply["id"])
        return Redirect(reply["invoice_url"])

    @staticmethod
    def signature(payload: dict, secret: str) -> str:
        message = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(secret.encode(), message.encode(), hashlib.sha512).hexdigest()

    def webhook(self, body: bytes, headers: dict) -> tuple[str, Verdict]:
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise GatewayError("Bad payload.")
        sent = headers.get("x-nowpayments-sig", "")
        if not sent or not hmac.compare_digest(sent, self.signature(payload, env("NOWPAYMENTS_IPN_SECRET"))):
            raise GatewayError("Bad signature.")
        status = str(payload.get("payment_status", ""))
        ref = str(payload.get("invoice_id") or "")
        receipt = str(payload.get("payment_id") or "")
        if status == "finished":
            return ref, Verdict("paid", receipt_ref=receipt, amount=_decimal(payload.get("actually_paid")), raw=payload)
        if status in ("failed", "refunded"):
            return ref, Verdict("failed", receipt_ref=receipt, reason=f"NOWPayments: {status}", raw=payload)
        if status == "expired":
            return ref, Verdict("expired", receipt_ref=receipt, raw=payload)
        # waiting / confirming / confirmed / sending / partially_paid
        return ref, Verdict("pending", receipt_ref=receipt, reason=status, raw=payload)


# ── Cryptomus ────────────────────────────────────────────────────────────────


def cryptomus_sign(payload: dict, key: str) -> str:
    # Cryptomus signs PHP json_encode output, which escapes "/" as "\/".
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("/", "\\/")
    return hashlib.md5(base64.b64encode(text.encode()) + key.encode()).hexdigest()  # noqa: S324 — Cryptomus's scheme


class Cryptomus(Gateway):
    key = "cryptomus"
    method = "crypto"
    currencies = ("USDT", "TON", "XRP")
    base = "https://api.cryptomus.com/v1"

    def configured(self) -> bool:
        return bool(env("CRYPTOMUS_MERCHANT_ID") and env("CRYPTOMUS_PAYMENT_KEY"))

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        c = coin(topup.asset)
        body = {
            "amount": format(topup.amount.normalize(), "f"),
            "currency": c.cryptomus_currency,
            "network": c.cryptomus_network,
            "order_id": str(topup.id).replace("-", ""),
            "url_callback": callback_url,
            "url_return": return_url,
            "url_success": return_url,
            "is_payment_multiple": False,
        }
        reply = http_json("POST", f"{self.base}/payment", body=body, headers={
            "merchant": env("CRYPTOMUS_MERCHANT_ID"),
            "sign": cryptomus_sign(body, env("CRYPTOMUS_PAYMENT_KEY")),
        })
        topup.log("cryptomus.payment", reply)
        result = reply.get("result") or {}
        if reply.get("state") != 0 or not result.get("uuid") or not result.get("url"):
            raise GatewayError(f"Cryptomus refused the payment ({reply.get('message') or 'unknown'}).")
        topup.gateway_ref = result["uuid"]
        return Redirect(result["url"])

    def webhook(self, body: bytes, headers: dict) -> tuple[str, Verdict]:
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise GatewayError("Bad payload.")
        sent = str(payload.pop("sign", ""))
        if not sent or not hmac.compare_digest(sent, cryptomus_sign(payload, env("CRYPTOMUS_PAYMENT_KEY"))):
            raise GatewayError("Bad signature.")
        status = str(payload.get("status", ""))
        ref = str(payload.get("uuid") or "")
        receipt = str(payload.get("txid") or "")
        if status in ("paid", "paid_over"):
            return ref, Verdict("paid", receipt_ref=receipt, amount=_decimal(payload.get("payment_amount")), raw=payload)
        if status in ("fail", "wrong_amount", "system_fail", "refund_paid", "cancel"):
            return ref, Verdict("failed", receipt_ref=receipt, reason=f"Cryptomus: {status}", raw=payload)
        return ref, Verdict("pending", receipt_ref=receipt, reason=status, raw=payload)


# ── Direct transfer to a registered platform wallet ──────────────────────────


class Direct(Gateway):
    """No third party: the payer transfers to our registered address and a
    superuser approves after checking the transaction on-chain."""

    key = "direct"
    method = "crypto"
    currencies = ("USDT", "TON", "XRP")
    manual = True

    def configured(self) -> bool:
        return True  # usable whenever an address is registered (checked by the service)
