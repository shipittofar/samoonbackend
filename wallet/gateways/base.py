"""Common pieces for top-up gateways.

A gateway adapter turns a TopUp into a payment page (``start``) and turns the
gateway's reply into a verdict (``confirm`` for bank callbacks, ``webhook``
for crypto notifications). Adapters never touch the wallet: the top-up
service credits it once a verdict says "paid".

Credentials come only from environment variables (server ``.env``), never
from the database or the platform panel.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger(__name__)

TIMEOUT = 20


class GatewayError(Exception):
    """The gateway refused or could not be reached; message is safe to show."""


@dataclass
class Redirect:
    """Where to send the payer: GET url, or POST a form with ``fields``."""

    url: str
    method: str = "GET"
    fields: dict = field(default_factory=dict)


@dataclass
class Verdict:
    status: str  # "paid" | "pending" | "failed" | "cancelled" | "expired"
    receipt_ref: str = ""
    card_pan: str = ""
    reason: str = ""
    raw: dict = field(default_factory=dict)
    # Crypto: the amount actually confirmed, in the top-up currency.
    amount: Decimal | None = None


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def env_flag(name: str) -> bool:
    return env(name).lower() in {"1", "true", "yes", "on"}


def http_json(method: str, url: str, *, body: dict | None = None, headers: dict | None = None) -> dict:
    """JSON request/response with a timeout; raises GatewayError on network
    errors and returns the parsed body for HTTP errors (gateways put their
    error codes there)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — fixed https gateway URLs
            text = resp.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace") or "{}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Gateway unreachable: %s %s (%s)", method, url, exc)
        raise GatewayError("The payment gateway could not be reached. Please try again.") from exc
    try:
        return json.loads(text)
    except ValueError:
        raise GatewayError("The payment gateway sent an unexpected reply.")


def http_raw(url: str, *, body: bytes, headers: dict) -> str:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError("The payment gateway could not be reached. Please try again.") from exc


def toman_to_rial(amount) -> int:
    """Iranian gateways take integer rials; wallets hold toman (1 toman = 10 rial)."""
    return int(Decimal(amount) * 10)


class Gateway:
    """Interface every adapter implements."""

    key: str = ""
    method: str = ""  # "bank" | "crypto"
    # Wallet currencies this gateway can credit.
    currencies: tuple[str, ...] = ()

    def configured(self) -> bool:
        """True when the server has this gateway's credentials."""
        raise NotImplementedError

    def start(self, topup, *, callback_url: str, return_url: str) -> Redirect:
        raise NotImplementedError

    def confirm(self, topup, params: dict) -> Verdict:
        """Bank gateways: the payer came back; verify with the gateway."""
        raise NotImplementedError

    def webhook(self, body: bytes, headers: dict) -> tuple[str, Verdict]:
        """Crypto gateways: (gateway reference, verdict) from a signed notification."""
        raise NotImplementedError
