"""Wallet top-ups: settings, start, bank callback, crypto webhook, direct
transfers and superuser review.

Rules that keep this safe:
* the wallet is credited only after a server-side confirmation (bank verify
  call, signed crypto webhook, or a superuser who checked a direct transfer);
* each top-up credits at most once (row lock + ledger idempotency key
  ``topup:<id>``);
* limits are checked before the payer pays, never after the money arrived;
* a crypto payer who underpays is credited what arrived, never more than asked.
"""
from __future__ import annotations

import logging
import re
import secrets
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from wallet import gateways, services
from wallet.gateways import COINS, GatewayError, Redirect, Verdict
from wallet.models import TopUp, TopUpMethod, TopUpStatus, TransactionKind

logger = logging.getLogger(__name__)

SETTINGS_KEY = "wallet.topup"
FINAL = {TopUpStatus.PAID, TopUpStatus.FAILED, TopUpStatus.CANCELLED, TopUpStatus.EXPIRED}

DEFAULTS: dict = {
    "bank": {"providers": [], "min": "10000", "max": "50000000"},  # toman
    "crypto": {
        "providers": [],
        "coins": {
            key: {"enabled": False, "min": "1" if c.currency != "USDT" else "5", "max": "10000", "address": ""}
            for key, c in COINS.items()
        },
    },
    # Unpaid gateway top-ups older than this are marked expired.
    "expire_minutes": 60,
}

# Receiving-address shapes per network (format check only; the superuser is
# responsible for the address being ours).
ADDRESS_PATTERNS = {
    "USDT_TRC20": re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$"),
    "USDT_BEP20": re.compile(r"^0x[0-9a-fA-F]{40}$"),
    "TON": re.compile(r"^([EU]Q[A-Za-z0-9_-]{46}|-?\d:[0-9a-fA-F]{64})$"),
    "XRP": re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$"),
}


# ── Settings ─────────────────────────────────────────────────────────────────


def _dec(value, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError({field: "Not a number."})
    if d < 0:
        raise ValidationError({field: "Must not be negative."})
    return d


def get_settings() -> dict:
    from platform_settings.models import PlatformSetting

    row = PlatformSetting.objects.filter(key=SETTINGS_KEY).first()
    stored = row.value if row and isinstance(row.value, dict) else {}
    bank = {**DEFAULTS["bank"], **(stored.get("bank") or {})}
    stored_crypto = stored.get("crypto") or {}
    coins = {
        key: {**DEFAULTS["crypto"]["coins"][key], **((stored_crypto.get("coins") or {}).get(key) or {})}
        for key in COINS
    }
    return {
        "bank": bank,
        "crypto": {"providers": list(stored_crypto.get("providers") or []), "coins": coins},
        "expire_minutes": int(stored.get("expire_minutes") or DEFAULTS["expire_minutes"]),
    }


def save_settings(data: dict, *, actor) -> dict:
    from platform_settings.models import PlatformSetting

    current = get_settings()
    bank_in = data.get("bank") or {}
    crypto_in = data.get("crypto") or {}

    bank_providers = [p for p in (bank_in.get("providers", current["bank"]["providers"]) or [])]
    unknown = [p for p in bank_providers if p not in gateways.BANK_GATEWAYS]
    if unknown:
        raise ValidationError({"bank.providers": f"Unknown: {', '.join(unknown)}"})
    bank_min = _dec(bank_in.get("min", current["bank"]["min"]), "bank.min")
    bank_max = _dec(bank_in.get("max", current["bank"]["max"]), "bank.max")
    if bank_max and bank_min > bank_max:
        raise ValidationError({"bank.min": "Minimum is above the maximum."})

    crypto_providers = list(crypto_in.get("providers", current["crypto"]["providers"]) or [])
    unknown = [p for p in crypto_providers if p not in gateways.CRYPTO_GATEWAYS]
    if unknown:
        raise ValidationError({"crypto.providers": f"Unknown: {', '.join(unknown)}"})

    coins: dict = {}
    for key in COINS:
        incoming = (crypto_in.get("coins") or {}).get(key) or {}
        row = {**current["crypto"]["coins"][key], **incoming}
        cmin, cmax = _dec(row.get("min") or 0, f"{key}.min"), _dec(row.get("max") or 0, f"{key}.max")
        if cmax and cmin > cmax:
            raise ValidationError({f"{key}.min": "Minimum is above the maximum."})
        address = str(row.get("address") or "").strip()
        if address and not ADDRESS_PATTERNS[key].match(address):
            raise ValidationError({f"{key}.address": f"Not a valid {COINS[key].network} address."})
        coins[key] = {"enabled": bool(row.get("enabled")), "min": str(cmin), "max": str(cmax), "address": address}

    expire = int(data.get("expire_minutes") or current["expire_minutes"])
    if not 5 <= expire <= 24 * 60:
        raise ValidationError({"expire_minutes": "Between 5 and 1440 minutes."})

    value = {
        "bank": {"providers": bank_providers, "min": str(bank_min), "max": str(bank_max)},
        "crypto": {"providers": crypto_providers, "coins": coins},
        "expire_minutes": expire,
    }
    from platform_settings.models import PlatformSettingChange

    row = PlatformSetting.objects.filter(key=SETTINGS_KEY).first()
    previous = row.value if row else None
    if row is None:
        row = PlatformSetting(key=SETTINGS_KEY)
    row.value = value
    row.updated_by = actor
    row.save()
    PlatformSettingChange.objects.create(key=SETTINGS_KEY, previous_value=previous, new_value=value, changed_by=actor)
    return get_settings()


def admin_settings() -> dict:
    """Settings plus which gateways have credentials on this server."""
    return {
        **get_settings(),
        "configured": {key: g.configured() for key, g in gateways.GATEWAYS.items() if key != "direct"},
        "sandbox": gateways.get("test").configured(),
    }


def options() -> dict:
    """What a customer can use right now (enabled in the panel and configured
    on the server)."""
    s = get_settings()
    bank = [p for p in s["bank"]["providers"] if gateways.get(p).configured()]
    crypto_providers = [p for p in s["crypto"]["providers"] if gateways.get(p).configured()]
    sandbox = gateways.get("test").configured()
    coins = []
    for key, row in s["crypto"]["coins"].items():
        providers = [p for p in crypto_providers if p != "direct" or row["address"]] if row["enabled"] else []
        if sandbox:  # dev/staging only: every coin through the test gateway
            providers.append("test")
        if providers:
            c = COINS[key]
            coins.append({
                "key": key, "currency": c.currency, "network": c.network, "min": row["min"], "max": row["max"],
                "providers": providers,
            })
    return {
        "bank": {"providers": bank + (["test"] if sandbox else []), "currency": "IRT", "min": s["bank"]["min"], "max": s["bank"]["max"]},
        "crypto": coins,
        "sandbox": sandbox,
    }


# ── Start ────────────────────────────────────────────────────────────────────


def _public_api(request) -> str:
    base = getattr(settings, "PUBLIC_API_URL", "") or ""
    return base.rstrip("/") if base else request.build_absolute_uri("/").rstrip("/")


def _new_order_number() -> int:
    return 10**11 + secrets.randbelow(9 * 10**11)  # 12 digits, fits every gateway


def start(*, user, method: str, provider: str, amount, asset: str = "", request) -> dict:
    s = get_settings()
    opts = options()
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise ValidationError({"amount": "Not a number."})
    if value <= 0:
        raise ValidationError({"amount": "Must be positive."})

    if method == TopUpMethod.BANK:
        if provider not in opts["bank"]["providers"]:
            raise ValidationError({"provider": "This gateway is not available."})
        currency, asset = "IRT", ""
        value = value.quantize(Decimal("1"))
        low, high = Decimal(s["bank"]["min"]), Decimal(s["bank"]["max"])
    elif method == TopUpMethod.CRYPTO:
        row = next((c for c in opts["crypto"] if c["key"] == asset), None)
        if provider == "test" and opts["sandbox"] and asset in COINS:
            row = row or s["crypto"]["coins"][asset]  # sandbox works before a coin is enabled
        elif not row or provider not in row["providers"]:
            raise ValidationError({"provider": "This coin or gateway is not available."})
        currency = COINS[asset].currency
        value = value.quantize(Decimal("0.0001"))
        low, high = Decimal(row["min"]), Decimal(row["max"])
    else:
        raise ValidationError({"method": "Choose bank or crypto."})
    if value < low or (high and value > high):
        raise ValidationError({"amount": f"Between {low} and {high} {currency}."})

    # Limits and freeze are checked now, before anybody pays.
    account = services.customer_account(user, currency)
    services._check_limits(account, value, limit_name="daily_topup", kinds=[TransactionKind.TOPUP])

    for _ in range(5):
        try:
            with transaction.atomic():
                topup = TopUp.objects.create(
                    user=user, method=method, provider=provider, currency=currency, amount=value, asset=asset,
                    order_number=_new_order_number(),
                )
            break
        except IntegrityError:
            continue
    else:  # pragma: no cover
        raise ValidationError({"detail": "Please try again."})

    if provider == "direct":
        address = s["crypto"]["coins"][asset]["address"]
        topup.status = TopUpStatus.PENDING
        topup.gateway_ref = f"DIRECT-{topup.order_number}"
        topup.log("direct.instructions", {"address": address})
        topup.save()
        return {"topup": serialize(topup), "instructions": instructions(topup)}

    gateway = gateways.get(provider)
    api = _public_api(request)
    callback = (
        f"{api}/api/wallet/topups/webhook/{provider}/"
        if gateway.method == "crypto"
        else f"{api}/api/wallet/topups/{topup.id}/callback/"
    )
    return_url = f"{settings.PUBLIC_SITE_URL}/dashboard/wallet?topup={topup.id}"
    try:
        redirect = gateway.start(topup, callback_url=callback, return_url=return_url)
    except GatewayError as exc:
        topup.status = TopUpStatus.FAILED
        topup.failure_reason = str(exc)[:300]
        topup.save()
        raise ValidationError({"detail": str(exc)})
    topup.status = TopUpStatus.PENDING
    topup.save()
    return {"topup": serialize(topup), "redirect": {"url": redirect.url, "method": redirect.method, "fields": redirect.fields}}


def instructions(topup: TopUp) -> dict | None:
    if topup.provider != "direct":
        return None
    c = COINS[topup.asset]
    address = next((e["data"].get("address") for e in topup.gateway_log if e.get("event") == "direct.instructions"), "")
    return {
        "address": address,
        "network": c.network,
        "coin": c.currency,
        "amount": format(topup.amount.normalize(), "f"),
        # TON comment / XRP destination tag identifies the payer on a shared address.
        "memo": str(topup.order_number) if c.needs_memo else "",
        "memoLabel": "Destination tag" if topup.asset == "XRP" else ("Comment" if c.needs_memo else ""),
    }


# ── Applying a verdict ───────────────────────────────────────────────────────


def _apply(topup: TopUp, verdict: Verdict, *, actor=None) -> TopUp:
    """Caller holds a row lock on ``topup``."""
    topup.log(f"verdict.{verdict.status}", {"receipt": verdict.receipt_ref, "reason": verdict.reason})
    if topup.status in FINAL:
        topup.save(update_fields=["gateway_log", "updated_at"])
        return topup
    if verdict.status == "paid":
        credited = topup.amount
        if verdict.amount is not None and verdict.amount < topup.amount:
            credited = verdict.amount  # underpaid crypto: credit what arrived
        topup.verified = True
        topup.receipt_ref = (verdict.receipt_ref or topup.receipt_ref)[:200]
        topup.card_pan = verdict.card_pan[:30]
        try:
            tx = services.credit_topup(
                user=topup.user, currency=topup.currency, amount=credited, reference=str(topup.id),
                metadata={"topupId": str(topup.id), "provider": topup.provider, "receipt": topup.receipt_ref},
                enforce_limits=False,
            )
        except Exception as exc:  # money arrived; keep it visible for a superuser to credit
            logger.exception("Top-up %s verified but not credited", topup.id)
            topup.failure_reason = f"Verified but not credited: {exc}"[:300]
            topup.save()
            return topup
        topup.status = TopUpStatus.PAID
        topup.ledger_transaction = tx
        topup.credited_amount = credited
        topup.paid_at = timezone.now()
        topup.failure_reason = ""
        topup.reviewed_by = actor
    elif verdict.status in ("failed", "cancelled", "expired"):
        topup.status = verdict.status
        topup.failure_reason = verdict.reason[:300]
    topup.save()
    return topup


def confirm(topup_id, params: dict) -> TopUp:
    """Bank callback: the payer came back from the gateway."""
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().get(id=topup_id)
        if topup.status in FINAL or topup.method == TopUpMethod.CRYPTO and topup.provider != "test":
            return topup
        gateway = gateways.get(topup.provider)
        try:
            verdict = gateway.confirm(topup, params)
        except GatewayError as exc:
            # Could not reach the gateway to verify: stay pending; the payer can retry the check.
            topup.log("confirm.error", {"error": str(exc)})
            topup.failure_reason = str(exc)[:300]
            topup.save()
            return topup
        return _apply(topup, verdict)


def webhook(provider: str, body: bytes, headers: dict) -> TopUp | None:
    gateway = gateways.get(provider)
    if gateway.method != "crypto" or provider == "direct":
        raise GatewayError("Not a webhook gateway.")
    ref, verdict = gateway.webhook(body, headers)  # raises on a bad signature
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().filter(provider=provider, gateway_ref=ref).first() if ref else None
        if topup is None:
            logger.warning("Webhook for unknown %s top-up %s", provider, ref)
            return None
        return _apply(topup, verdict)


# ── Customer actions ─────────────────────────────────────────────────────────


def submit_tx(*, user, topup_id, tx_hash: str) -> TopUp:
    tx_hash = (tx_hash or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9:_\-]{16,200}", tx_hash):
        raise ValidationError({"txHash": "Enter the transaction hash."})
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().get(id=topup_id, user=user)
        if topup.provider != "direct" or topup.status != TopUpStatus.PENDING:
            raise ValidationError({"detail": "This top-up does not take a transaction hash."})
        if TopUp.objects.filter(provider="direct", receipt_ref=tx_hash).exclude(id=topup.id).exists():
            raise ValidationError({"txHash": "This transaction was already submitted."})
        topup.receipt_ref = tx_hash
        topup.log("direct.submitted", {"tx": tx_hash})
        topup.save()
    return topup


def cancel(*, user, topup_id) -> TopUp:
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().get(id=topup_id, user=user)
        if topup.status in FINAL or topup.verified or topup.receipt_ref:
            raise ValidationError({"detail": "This top-up can no longer be cancelled."})
        topup.status = TopUpStatus.CANCELLED
        topup.failure_reason = "Cancelled by the payer."
        topup.save()
    return topup


def expire_stale() -> int:
    """Gateway top-ups nobody finished. Direct transfers with a submitted hash
    stay for review; crypto invoices are left to their webhook."""
    minutes = get_settings()["expire_minutes"]
    cutoff = timezone.now() - timezone.timedelta(minutes=minutes)
    stale = TopUp.objects.filter(status__in=[TopUpStatus.CREATED, TopUpStatus.PENDING], created_at__lt=cutoff, verified=False)
    stale = stale.exclude(provider__in=["nowpayments", "cryptomus"]).exclude(provider="direct", receipt_ref__gt="")
    return stale.update(status=TopUpStatus.EXPIRED, failure_reason="Not completed in time.", updated_at=timezone.now())


# ── Superuser review ─────────────────────────────────────────────────────────


def approve(*, topup_id, actor, amount=None, note: str = "") -> TopUp:
    """Credit a direct transfer after checking it on-chain, or a gateway
    top-up that was verified but could not be credited."""
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().get(id=topup_id)
        if topup.status == TopUpStatus.PAID:
            return topup
        if topup.provider != "direct" and not topup.verified:
            raise ValidationError({"detail": "Only direct transfers or verified payments can be approved by hand."})
        value = None
        if amount not in (None, ""):
            value = _dec(amount, "amount")
            if value <= 0 or value > topup.amount:
                raise ValidationError({"amount": "Between 0 and the requested amount."})
        topup.log("admin.approve", {"by": str(actor.pk), "amount": str(value) if value else None, "note": note[:200]})
        topup.status = TopUpStatus.PENDING if topup.status in FINAL else topup.status
        return _apply(topup, Verdict("paid", receipt_ref=topup.receipt_ref, amount=value), actor=actor)


def reject(*, topup_id, actor, reason: str) -> TopUp:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required."})
    with transaction.atomic():
        topup = TopUp.objects.select_for_update().get(id=topup_id)
        if topup.status == TopUpStatus.PAID:
            raise ValidationError({"detail": "Already credited; use a wallet adjustment instead."})
        topup.log("admin.reject", {"by": str(actor.pk), "reason": reason[:200]})
        topup.status = TopUpStatus.FAILED
        topup.failure_reason = reason[:300]
        topup.reviewed_by = actor
        topup.save()
    return topup


# ── Serialization ────────────────────────────────────────────────────────────


def _num(d) -> str | None:
    return None if d is None else format(Decimal(d).normalize(), "f")


def serialize(t: TopUp, *, admin: bool = False) -> dict:
    data = {
        "id": str(t.id),
        "orderNumber": t.order_number,
        "method": t.method,
        "provider": t.provider,
        "currency": t.currency,
        "asset": t.asset,
        "amount": _num(t.amount),
        "creditedAmount": _num(t.credited_amount),
        "status": t.status,
        "receiptRef": t.receipt_ref,
        "cardPan": t.card_pan,
        "failureReason": t.failure_reason,
        "verified": t.verified,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
        "paidAt": t.paid_at.isoformat() if t.paid_at else None,
        "instructions": instructions(t),
    }
    if admin:
        u = t.user
        data["user"] = {
            "id": str(u.pk),
            "name": (u.get_full_name() if hasattr(u, "get_full_name") else "") or "",
            "phone": getattr(u, "phone_number", "") or "",
            "email": u.email or "",
        }
        data["gatewayRef"] = t.gateway_ref
        data["log"] = t.gateway_log
        data["reviewedBy"] = str(t.reviewed_by_id) if t.reviewed_by_id else None
    return data


# Keep Redirect importable for callers that build their own.
__all__ = ["Redirect", "approve", "cancel", "confirm", "expire_stale", "get_settings", "options", "reject", "save_settings", "serialize", "start", "submit_tx", "webhook"]
