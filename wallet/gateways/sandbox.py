"""Test gateway for development and staging: a page on our own frontend that
lets you choose success or failure. Disabled unless WALLET_TEST_GATEWAY=1.

The callback carries an HMAC of (top-up id, outcome) keyed by SECRET_KEY, so
it cannot be forged by editing the URL.
"""
from __future__ import annotations

import hashlib
import hmac

from django.conf import settings

from wallet.gateways.base import Gateway, Redirect, Verdict, env_flag


def sandbox_token(topup_id, outcome: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{topup_id}:{outcome}".encode(), hashlib.sha256).hexdigest()[:32]


class SandboxGateway(Gateway):
    key = "test"
    method = "bank"
    currencies = ("IRT", "USDT", "TON", "XRP", "USD", "EUR")

    def configured(self) -> bool:
        return env_flag("WALLET_TEST_GATEWAY")

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        topup.gateway_ref = f"TEST-{topup.order_number}"
        return Redirect(
            f"{return_url.split('?')[0]}/topup-test",
            fields={
                "id": str(topup.id),
                "callback": callback_url,
                "ok": sandbox_token(topup.id, "ok"),
                "cancel": sandbox_token(topup.id, "cancel"),
            },
        )

    def confirm(self, topup, params) -> Verdict:
        outcome = params.get("outcome", "")
        if outcome not in ("ok", "cancel") or not hmac.compare_digest(str(params.get("token", "")), sandbox_token(topup.id, outcome)):
            return Verdict("failed", reason="Bad test token.")
        if outcome == "ok":
            return Verdict("paid", receipt_ref=f"TEST-{topup.order_number}", card_pan="6037****1234")
        return Verdict("cancelled", reason="Cancelled on the test page.")
