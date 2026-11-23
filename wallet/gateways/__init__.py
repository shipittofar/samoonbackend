"""Top-up gateway registry."""
from __future__ import annotations

from wallet.gateways.bank import IDPay, Mellat, Sadad, Zarinpal
from wallet.gateways.base import Gateway, GatewayError, Redirect, Verdict
from wallet.gateways.crypto import COINS, Coin, Cryptomus, Direct, NOWPayments, coin
from wallet.gateways.sandbox import SandboxGateway

GATEWAYS: dict[str, Gateway] = {
    g.key: g for g in (Zarinpal(), IDPay(), Mellat(), Sadad(), NOWPayments(), Cryptomus(), Direct(), SandboxGateway())
}

BANK_GATEWAYS = ("zarinpal", "idpay", "mellat", "sadad")
CRYPTO_GATEWAYS = ("nowpayments", "cryptomus", "direct")


def get(key: str) -> Gateway:
    try:
        return GATEWAYS[key]
    except KeyError:
        raise GatewayError("Unknown payment gateway.")


__all__ = [
    "BANK_GATEWAYS", "COINS", "CRYPTO_GATEWAYS", "Coin", "GATEWAYS", "Gateway", "GatewayError",
    "Redirect", "Verdict", "coin", "get",
]
