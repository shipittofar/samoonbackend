"""Settlement with business owners: commission, hold period, payouts.

Every money move goes through wallet.services.post (balanced, idempotent,
locked). Payouts are made by hand: a superuser sends the money from the
platform's bank account or crypto wallet and records the reference here.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from settlement.models import (
    OrderSettlement,
    Payout,
    PayoutAccount,
    PayoutAccountKind,
    PayoutAccountStatus,
    PayoutStatus,
    SettlementStatus,
    TenantSettlementTerms,
)
from wallet import services as wallet
from wallet.models import AccountKind, LedgerEntry, LedgerTransaction, TransactionKind, WalletAccount

logger = logging.getLogger(__name__)

SETTINGS_KEY = "settlement"
TERMS_KEY = "settlement.terms"
DONE_STATUSES = {"served", "delivered", "picked_up", "completed"}
BUSINESS_KINDS = (AccountKind.BUSINESS, AccountKind.BUSINESS_PENDING, AccountKind.BUSINESS_RESERVED)
MAX_COMMISSION = Decimal("50")
MAX_HOLD_DAYS = 60

DEFAULTS: dict = {
    "commission_percent": "0",
    "hold_days": 3,
    # Smallest payout a business can request, per currency.
    "min_payout": {"IRT": "100000", "USDT": "10", "TON": "5", "XRP": "10"},
    # Weekly automatic payout requests (still paid by hand). Off until a
    # superuser turns it on. weekday: Python numbering, Monday = 0, Saturday = 5.
    "auto_payout": {"enabled": False, "weekday": 5},
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dec(value, field: str, *, allow_empty: bool = False) -> Decimal | None:
    if value in (None, "") and allow_empty:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({field: "Not a number."})
    if not d.is_finite():
        raise ValidationError({field: "Not a number."})
    return d


def _round(amount: Decimal, currency: str) -> Decimal:
    from currencies import services as currencies

    info = currencies.table().get(currency.upper())
    if info is not None:
        return currencies.round_to(amount, info, use_step=False)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _num(value) -> str:
    return format(Decimal(value).normalize(), "f") if value is not None else "0"


def is_owner(user, tenant) -> bool:
    owner = getattr(tenant, "owner", None)
    return bool(owner and owner.user_id == user.pk)


def check_access(user, tenant) -> None:
    """Payout accounts and money: the business owner and platform superusers only."""
    from access.authorization.platform import is_platform_superuser

    if is_owner(user, tenant) or is_platform_superuser(user):
        return
    raise PermissionDenied("Only the business owner can manage settlement.")


# ── Settings and terms ───────────────────────────────────────────────────────


def get_settings() -> dict:
    from platform_settings.models import PlatformSetting

    row = PlatformSetting.objects.filter(key=SETTINGS_KEY).first()
    stored = row.value if row and isinstance(row.value, dict) else {}
    return {
        "commission_percent": str(stored.get("commission_percent", DEFAULTS["commission_percent"])),
        "hold_days": int(stored.get("hold_days", DEFAULTS["hold_days"])),
        "min_payout": {**DEFAULTS["min_payout"], **(stored.get("min_payout") or {})},
        "auto_payout": {**DEFAULTS["auto_payout"], **(stored.get("auto_payout") or {})},
    }


def _check_rate(value, field) -> Decimal:
    rate = _dec(value, field)
    if not Decimal("0") <= rate <= MAX_COMMISSION:
        raise ValidationError({field: f"Between 0 and {MAX_COMMISSION}."})
    return rate.quantize(Decimal("0.01"))


def _check_hold(value, field) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise ValidationError({field: "A whole number of days."})
    if not 0 <= days <= MAX_HOLD_DAYS:
        raise ValidationError({field: f"Between 0 and {MAX_HOLD_DAYS} days."})
    return days


def save_settings(data: dict, *, actor) -> dict:
    from platform_settings.models import PlatformSetting, PlatformSettingChange

    current = get_settings()
    rate = _check_rate(data.get("commission_percent", current["commission_percent"]), "commission_percent")
    hold = _check_hold(data.get("hold_days", current["hold_days"]), "hold_days")
    mins: dict[str, str] = {}
    for code, value in {**current["min_payout"], **(data.get("min_payout") or {})}.items():
        if value in (None, ""):
            continue
        d = _dec(value, f"min_payout.{code}")
        if d < 0:
            raise ValidationError({f"min_payout.{code}": "Must not be negative."})
        mins[str(code).upper()] = str(d)
    auto_in = {**current["auto_payout"], **(data.get("auto_payout") or {})}
    weekday = int(auto_in.get("weekday", 5))
    if not 0 <= weekday <= 6:
        raise ValidationError({"auto_payout.weekday": "0 (Monday) to 6 (Sunday)."})
    value = {
        "commission_percent": str(rate),
        "hold_days": hold,
        "min_payout": mins,
        "auto_payout": {"enabled": bool(auto_in.get("enabled")), "weekday": weekday},
    }
    row = PlatformSetting.objects.filter(key=SETTINGS_KEY).first()
    previous = row.value if row else None
    if row is None:
        row = PlatformSetting(key=SETTINGS_KEY)
    row.value = value
    row.updated_by = actor
    row.save()
    PlatformSettingChange.objects.create(key=SETTINGS_KEY, previous_value=previous, new_value=value, changed_by=actor)
    return get_settings()


def terms_for(tenant) -> dict:
    s = get_settings()
    own = TenantSettlementTerms.objects.filter(tenant=tenant).first()
    rate = own.commission_percent if own and own.commission_percent is not None else Decimal(s["commission_percent"])
    hold = own.hold_days if own and own.hold_days is not None else s["hold_days"]
    return {
        "commissionPercent": _num(rate),
        "holdDays": hold,
        "commissionIsCustom": bool(own and own.commission_percent is not None),
        "holdIsCustom": bool(own and own.hold_days is not None),
        "note": own.note if own else "",
        "platformCommissionPercent": s["commission_percent"],
        "platformHoldDays": s["hold_days"],
    }


def set_terms(tenant, *, data: dict, actor) -> dict:
    """Per-business override; an empty value goes back to the platform default."""
    from platform_settings.models import PlatformSettingChange

    rate = data.get("commissionPercent")
    hold = data.get("holdDays")
    own, _ = TenantSettlementTerms.objects.get_or_create(tenant=tenant)
    previous = {"commission_percent": _num(own.commission_percent) if own.commission_percent is not None else None,
                "hold_days": own.hold_days, "note": own.note}
    own.commission_percent = None if rate in (None, "") else _check_rate(rate, "commissionPercent")
    own.hold_days = None if hold in (None, "") else _check_hold(hold, "holdDays")
    own.note = str(data.get("note") or "")[:300]
    own.updated_by = actor
    own.save()
    PlatformSettingChange.objects.create(
        key=TERMS_KEY, tenant=tenant, previous_value=previous, changed_by=actor,
        new_value={"commission_percent": _num(own.commission_percent) if own.commission_percent is not None else None,
                   "hold_days": own.hold_days, "note": own.note},
    )
    return terms_for(tenant)


# ── Orders ───────────────────────────────────────────────────────────────────


def _payment_tx(order) -> LedgerTransaction | None:
    tx = LedgerTransaction.objects.filter(order=order, kind=TransactionKind.ORDER_PAYMENT).first()
    if tx is None or hasattr(tx, "reversed_by"):
        return None
    return tx


def on_order_done(order) -> OrderSettlement | None:
    """The order reached served / delivered / picked up / completed: record
    what the business earns and charge the platform commission. Runs once per
    order, inside the order's database transaction."""
    if order.status not in DONE_STATUSES:
        return None
    existing = OrderSettlement.objects.filter(order=order).first()
    if existing:
        return existing
    tenant = order.branch.tenant
    currency = (order.currency or "IRT").upper()
    gross = wallet._amount(order.total)
    if gross <= 0:
        return None
    terms = terms_for(tenant)
    rate = Decimal(terms["commissionPercent"])
    commission = _round(gross * rate / 100, currency)
    now = timezone.now()
    payment = _payment_tx(order)
    via_wallet = payment is not None
    # Older wallet orders (before the hold account existed) credited "business" directly.
    held = via_wallet and payment.entries.filter(account__kind=AccountKind.BUSINESS_PENDING).exists()

    row = OrderSettlement(
        order=order, tenant=tenant, currency=currency, gross=gross, commission_percent=rate,
        commission=commission, net=gross - commission, via_wallet=via_wallet, completed_at=now,
    )
    if commission > 0:
        source = wallet.business_account(
            tenant, currency, AccountKind.BUSINESS_PENDING if held else AccountKind.BUSINESS
        )
        row.commission_tx = wallet.post(
            kind=TransactionKind.COMMISSION,
            currency=currency,
            legs=[wallet.Leg(source, -commission), wallet.Leg(wallet.system_account(AccountKind.SYSTEM_REVENUE, currency), commission)],
            idempotency_key=f"commission:{order.id}",
            order=order,
            description=f"Commission {rate}% on order {order.order_number}",
            metadata={"rate": str(rate), "gross": str(gross)},
        )
    if held:
        row.status = SettlementStatus.HELD
        row.release_after = now + timezone.timedelta(days=terms["holdDays"])
    elif via_wallet:
        row.status = SettlementStatus.RELEASED
        row.released_at = now
    else:
        row.status = SettlementStatus.CHARGED
    row.save()
    if row.status == SettlementStatus.HELD and terms["holdDays"] == 0:
        _release(row)
    return row


def _release(row: OrderSettlement) -> None:
    """Caller holds a lock on ``row`` (or just created it)."""
    if row.status != SettlementStatus.HELD:
        return
    if row.net > 0:
        tenant = row.tenant
        row.release_tx = wallet.post(
            kind=TransactionKind.RELEASE,
            currency=row.currency,
            legs=[
                wallet.Leg(wallet.business_account(tenant, row.currency, AccountKind.BUSINESS_PENDING), -row.net),
                wallet.Leg(wallet.business_account(tenant, row.currency, AccountKind.BUSINESS), row.net),
            ],
            idempotency_key=f"release:{row.order_id}",
            order=row.order,
            description=f"Order {row.order.order_number} released",
        )
    row.status = SettlementStatus.RELEASED
    row.released_at = timezone.now()
    row.save(update_fields=["status", "released_at", "release_tx"])


def release_due(*, tenant=None, now=None) -> int:
    """Move every finished hold period to the available balance."""
    now = now or timezone.now()
    qs = OrderSettlement.objects.filter(status=SettlementStatus.HELD, release_after__lte=now)
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    done = 0
    for pk in list(qs.values_list("pk", flat=True)[:500]):
        try:
            with transaction.atomic():
                row = OrderSettlement.objects.select_for_update().select_related("order", "tenant").get(pk=pk)
                if row.status == SettlementStatus.HELD:
                    _release(row)
                    done += 1
        except Exception:
            logger.exception("Could not release settlement %s", pk)
    return done


# ── Balances and statement ───────────────────────────────────────────────────


def balances(tenant) -> list[dict]:
    rows: dict[str, dict] = {}
    for a in WalletAccount.objects.filter(tenant=tenant, kind__in=BUSINESS_KINDS):
        row = rows.setdefault(a.currency, {"currency": a.currency, "available": Decimal(0), "pending": Decimal(0), "reserved": Decimal(0)})
        key = {"business": "available", "business_pending": "pending", "business_reserved": "reserved"}[a.kind]
        row[key] += a.balance
    return [
        {
            "currency": r["currency"],
            "available": _num(r["available"]),
            "pending": _num(r["pending"]),
            "reserved": _num(r["reserved"]),
            # Negative available = commission the business owes (cash/card orders).
            "owed": _num(-r["available"]) if r["available"] < 0 else "0",
            "nextRelease": _next_release(tenant, r["currency"]),
        }
        for r in sorted(rows.values(), key=lambda r: r["currency"])
    ]


def _next_release(tenant, currency) -> str | None:
    row = (
        OrderSettlement.objects.filter(tenant=tenant, currency=currency, status=SettlementStatus.HELD)
        .order_by("release_after").first()
    )
    return row.release_after.isoformat() if row and row.release_after else None


KIND_LABEL = {
    "order_payment": "order_payment",
    "order_refund": "order_refund",
    "commission": "commission",
    "settlement_release": "release",
    "payout_hold": "payout_hold",
    "payout": "payout",
    "payout_return": "payout_return",
}


def _entries(tenant, params):
    qs = LedgerEntry.objects.filter(account__tenant=tenant, account__kind__in=BUSINESS_KINDS)
    currency = (params.get("currency") or "").upper()
    if currency:
        qs = qs.filter(account__currency=currency)
    if params.get("from"):
        qs = qs.filter(created_at__date__gte=params["from"])
    if params.get("to"):
        qs = qs.filter(created_at__date__lte=params["to"])
    return qs.select_related("transaction__order", "account").order_by("-created_at", "-id")


def _line(e: LedgerEntry) -> dict:
    tx = e.transaction
    order = tx.order
    return {
        "id": e.id,
        "kind": KIND_LABEL.get(tx.kind, tx.kind),
        "bucket": {"business": "available", "business_pending": "pending", "business_reserved": "reserved"}[e.account.kind],
        "currency": e.account.currency,
        "amount": _num(e.amount),
        "balanceAfter": _num(e.balance_after),
        "orderId": str(order.id) if order else None,
        "orderNumber": order.order_number if order else None,
        "description": tx.description,
        "createdAt": e.created_at.isoformat(),
    }


def statement(tenant, params) -> dict:
    qs = _entries(tenant, params)
    try:
        page = max(1, int(params.get("page", 1)))
        size = min(100, max(1, int(params.get("pageSize", 25))))
    except ValueError:
        page, size = 1, 25
    count = qs.count()
    return {"results": [_line(e) for e in qs[(page - 1) * size: page * size]], "count": count, "page": page, "pageSize": size}


def statement_csv(tenant, params) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["date", "type", "bucket", "currency", "amount", "balance_after", "order", "description"])
    for e in _entries(tenant, params)[:20000]:
        line = _line(e)
        writer.writerow([
            line["createdAt"], line["kind"], line["bucket"], line["currency"], line["amount"],
            line["balanceAfter"], line["orderNumber"] or "", _csv_safe(line["description"]),
        ])
    return out.getvalue()


def _csv_safe(text: str) -> str:
    # Spreadsheet formula injection: never start a cell with = + - @.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def order_settlements(tenant, params) -> dict:
    qs = OrderSettlement.objects.filter(tenant=tenant).select_related("order")
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    count = qs.count()
    rows = qs[(page - 1) * 25: page * 25]
    return {
        "results": [
            {
                "orderId": str(r.order_id), "orderNumber": r.order.order_number, "currency": r.currency,
                "gross": _num(r.gross), "commissionPercent": _num(r.commission_percent), "commission": _num(r.commission),
                "net": _num(r.net), "viaWallet": r.via_wallet, "status": r.status,
                "completedAt": r.completed_at.isoformat(),
                "releaseAfter": r.release_after.isoformat() if r.release_after else None,
            }
            for r in rows
        ],
        "count": count, "page": page, "pageSize": 25,
    }


# ── Payout accounts ──────────────────────────────────────────────────────────

IBAN_RE = re.compile(r"^IR\d{24}$")


def valid_iban(iban: str) -> bool:
    if not IBAN_RE.match(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def serialize_account(a: PayoutAccount) -> dict:
    return {
        "id": str(a.id), "kind": a.kind, "currency": a.currency, "iban": a.iban, "holderName": a.holder_name,
        "bankName": a.bank_name, "asset": a.asset, "address": a.address, "memo": a.memo, "label": a.label,
        "isDefault": a.is_default, "status": a.status, "reviewNote": a.review_note,
        "createdAt": a.created_at.isoformat(), "reviewedAt": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "tenantId": str(a.tenant_id),
    }


def add_account(tenant, *, data: dict, actor) -> PayoutAccount:
    from wallet.gateways.crypto import COINS
    from wallet.topups import ADDRESS_PATTERNS

    kind = data.get("kind")
    fields: dict = {"label": str(data.get("label") or "")[:80]}
    if kind == PayoutAccountKind.IBAN:
        iban = re.sub(r"[\s-]", "", str(data.get("iban") or "")).upper()
        if not iban.startswith("IR"):
            iban = "IR" + iban
        if not valid_iban(iban):
            raise ValidationError({"iban": "Not a valid Sheba number (IR + 24 digits)."})
        holder = str(data.get("holderName") or "").strip()
        if not holder:
            raise ValidationError({"holderName": "Enter the account holder's name."})
        fields.update(currency="IRT", iban=iban, holder_name=holder[:120], bank_name=str(data.get("bankName") or "")[:80])
    elif kind == PayoutAccountKind.CRYPTO:
        asset = str(data.get("asset") or "")
        if asset not in COINS:
            raise ValidationError({"asset": "Choose a coin and network."})
        address = str(data.get("address") or "").strip()
        if not ADDRESS_PATTERNS[asset].match(address):
            raise ValidationError({"address": f"Not a valid {COINS[asset].network} address."})
        fields.update(currency=COINS[asset].currency, asset=asset, address=address, memo=str(data.get("memo") or "")[:60])
    else:
        raise ValidationError({"kind": "Choose a bank account or a crypto wallet."})
    if PayoutAccount.objects.filter(tenant=tenant, status__in=["pending", "approved"]).filter(
        iban=fields.get("iban", ""), address=fields.get("address", "")
    ).exists():
        raise ValidationError({"detail": "This account is already registered."})
    account = PayoutAccount.objects.create(tenant=tenant, kind=kind, created_by=actor, **fields)
    _notify_superusers("settlement_account_submitted", tenant, account, actor)
    return account


def review_account(account_id, *, approve: bool, actor, note: str = "") -> PayoutAccount:
    with transaction.atomic():
        account = PayoutAccount.objects.select_for_update().select_related("tenant").get(id=account_id)
        if account.status != PayoutAccountStatus.PENDING:
            raise ValidationError({"detail": "This account was already reviewed."})
        if not approve and not note.strip():
            raise ValidationError({"note": "A reason is required."})
        account.status = PayoutAccountStatus.APPROVED if approve else PayoutAccountStatus.REJECTED
        account.review_note = note.strip()[:300]
        account.reviewed_by = actor
        account.reviewed_at = timezone.now()
        if approve and not PayoutAccount.objects.filter(
            tenant=account.tenant, currency=account.currency, status=PayoutAccountStatus.APPROVED, is_default=True
        ).exists():
            account.is_default = True
        account.save()
    _notify_owner("settlement_account_approved" if approve else "settlement_account_rejected", account.tenant, actor, {
        "account": _account_label(account), "reason": account.review_note,
    })
    return account


def disable_account(tenant, account_id, *, actor) -> PayoutAccount:
    with transaction.atomic():
        account = PayoutAccount.objects.select_for_update().get(id=account_id, tenant=tenant)
        if Payout.objects.filter(account=account, status=PayoutStatus.REQUESTED).exists():
            raise ValidationError({"detail": "A payout to this account is still open."})
        account.status = PayoutAccountStatus.DISABLED
        account.is_default = False
        account.save(update_fields=["status", "is_default"])
    return account


def make_default(tenant, account_id) -> PayoutAccount:
    with transaction.atomic():
        account = PayoutAccount.objects.select_for_update().get(id=account_id, tenant=tenant)
        if account.status != PayoutAccountStatus.APPROVED:
            raise ValidationError({"detail": "Only an approved account can be the default."})
        PayoutAccount.objects.filter(tenant=tenant, currency=account.currency).exclude(id=account.id).update(is_default=False)
        account.is_default = True
        account.save(update_fields=["is_default"])
    return account


def _account_label(a: PayoutAccount) -> str:
    if a.kind == PayoutAccountKind.IBAN:
        return f"{a.iban[:6]}…{a.iban[-4:]} ({a.holder_name})"
    return f"{a.asset} {a.address[:6]}…{a.address[-4:]}"


# ── Payouts ──────────────────────────────────────────────────────────────────


def serialize_payout(p: Payout, *, admin: bool = False) -> dict:
    data = {
        "id": str(p.id), "currency": p.currency, "amount": _num(p.amount), "status": p.status,
        "automatic": p.automatic, "reference": p.reference, "note": p.note,
        "account": serialize_account(p.account), "createdAt": p.created_at.isoformat(),
        "processedAt": p.processed_at.isoformat() if p.processed_at else None,
    }
    if admin:
        data["tenant"] = {"id": str(p.tenant_id), "name": p.tenant.name}
    return data


def request_payout(tenant, *, account_id, amount, actor, automatic: bool = False, note: str = "") -> Payout:
    value = wallet._amount(_dec(amount, "amount"))
    if value <= 0:
        raise ValidationError({"amount": "Must be positive."})
    with transaction.atomic():
        account = PayoutAccount.objects.select_for_update().filter(id=account_id, tenant=tenant).first()
        if account is None or account.status != PayoutAccountStatus.APPROVED:
            raise ValidationError({"account": "Choose an approved payout account."})
        currency = account.currency
        minimum = get_settings()["min_payout"].get(currency)
        if minimum and value < Decimal(minimum):
            raise ValidationError({"amount": f"The minimum payout is {minimum} {currency}."})
        available = wallet.business_account(tenant, currency)
        available = WalletAccount.objects.select_for_update().get(pk=available.pk)
        if value > available.balance:
            raise ValidationError({"amount": f"More than the available balance ({_num(available.balance)} {currency})."})
        payout = Payout(tenant=tenant, account=account, currency=currency, amount=value, automatic=automatic,
                        requested_by=actor, note=note[:300])
        payout.hold_tx = wallet.post(
            kind=TransactionKind.PAYOUT_HOLD,
            currency=currency,
            legs=[
                wallet.Leg(available, -value),
                wallet.Leg(wallet.business_account(tenant, currency, AccountKind.BUSINESS_RESERVED), value),
            ],
            idempotency_key=f"payout-hold:{payout.id}",
            description=f"Payout requested to {_account_label(account)}",
            created_by=actor,
        )
        payout.save()
    _notify_superusers("settlement_payout_requested", tenant, payout, actor)
    return payout


def _close(payout: Payout, *, paid: bool, actor, description: str) -> None:
    tenant, currency, value = payout.tenant, payout.currency, payout.amount
    reserved = wallet.business_account(tenant, currency, AccountKind.BUSINESS_RESERVED)
    target = (
        wallet.system_account(AccountKind.SYSTEM_PAYOUT, currency) if paid else wallet.business_account(tenant, currency)
    )
    payout.close_tx = wallet.post(
        kind=TransactionKind.PAYOUT if paid else TransactionKind.PAYOUT_RETURN,
        currency=currency,
        legs=[wallet.Leg(reserved, -value), wallet.Leg(target, value)],
        idempotency_key=f"payout-close:{payout.id}",
        description=description,
        created_by=actor,
    )


def cancel_payout(tenant, payout_id, *, actor) -> Payout:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("tenant", "account").get(id=payout_id, tenant=tenant)
        if payout.status != PayoutStatus.REQUESTED:
            raise ValidationError({"detail": "Only an open request can be cancelled."})
        _close(payout, paid=False, actor=actor, description="Payout request cancelled")
        payout.status = PayoutStatus.CANCELLED
        payout.processed_at = timezone.now()
        payout.save()
    return payout


def mark_paid(payout_id, *, actor, reference: str, note: str = "") -> Payout:
    reference = (reference or "").strip()
    if not reference:
        raise ValidationError({"reference": "Enter the bank tracking number or transaction hash."})
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("tenant", "account").get(id=payout_id)
        if payout.status != PayoutStatus.REQUESTED:
            raise ValidationError({"detail": "This payout is already closed."})
        _close(payout, paid=True, actor=actor, description=f"Paid out, ref {reference[:80]}")
        payout.status = PayoutStatus.PAID
        payout.reference = reference[:200]
        payout.note = (note or payout.note)[:300]
        payout.processed_by = actor
        payout.processed_at = timezone.now()
        payout.save()
    _notify_owner("settlement_payout_paid", payout.tenant, actor, {
        "amount": wallet_money(payout.amount), "currency": payout.currency, "reference": payout.reference,
        "account": _account_label(payout.account),
    })
    return payout


def reject_payout(payout_id, *, actor, reason: str) -> Payout:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required."})
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("tenant", "account").get(id=payout_id)
        if payout.status != PayoutStatus.REQUESTED:
            raise ValidationError({"detail": "This payout is already closed."})
        _close(payout, paid=False, actor=actor, description=f"Payout rejected: {reason[:200]}")
        payout.status = PayoutStatus.REJECTED
        payout.note = reason[:300]
        payout.processed_by = actor
        payout.processed_at = timezone.now()
        payout.save()
    _notify_owner("settlement_payout_rejected", payout.tenant, actor, {
        "amount": wallet_money(payout.amount), "currency": payout.currency, "reason": reason[:200],
    })
    return payout


def wallet_money(value) -> str:
    from notifications.events import _money

    return _money(value)


def run_auto_payouts(*, now=None) -> int:
    """Weekly automatic payout requests (paid by hand like any other). Does
    nothing unless a superuser turned it on in the platform panel."""
    s = get_settings()
    auto = s["auto_payout"]
    now = now or timezone.now()
    if not auto.get("enabled") or now.weekday() != int(auto.get("weekday", 5)):
        return 0
    week_ago = now - timezone.timedelta(days=6)
    created = 0
    accounts = PayoutAccount.objects.filter(status=PayoutAccountStatus.APPROVED, is_default=True).select_related("tenant")
    for account in accounts:
        tenant = account.tenant
        if Payout.objects.filter(tenant=tenant, currency=account.currency, automatic=True, created_at__gte=week_ago).exists():
            continue
        balance = wallet.business_account(tenant, account.currency).balance
        minimum = Decimal(s["min_payout"].get(account.currency) or "0")
        if balance <= 0 or balance < minimum:
            continue
        try:
            request_payout(tenant, account_id=account.id, amount=balance, actor=None, automatic=True, note="Weekly payout")
            created += 1
        except Exception:
            logger.exception("Automatic payout for %s failed", tenant.pk)
    return created


def run_scheduled() -> dict:
    return {"released": release_due(), "autoPayouts": run_auto_payouts()}


# ── Platform overview ────────────────────────────────────────────────────────


def platform_overview() -> dict:
    totals: dict[str, dict] = {}
    for a in WalletAccount.objects.filter(kind__in=[*BUSINESS_KINDS, AccountKind.SYSTEM_REVENUE, AccountKind.SYSTEM_PAYOUT]):
        row = totals.setdefault(a.currency, {k: Decimal(0) for k in ("available", "owed", "pending", "reserved", "revenue", "paidOut")})
        if a.kind == AccountKind.BUSINESS:
            if a.balance >= 0:
                row["available"] += a.balance
            else:
                row["owed"] += -a.balance
        elif a.kind == AccountKind.BUSINESS_PENDING:
            row["pending"] += a.balance
        elif a.kind == AccountKind.BUSINESS_RESERVED:
            row["reserved"] += a.balance
        elif a.kind == AccountKind.SYSTEM_REVENUE:
            row["revenue"] += a.balance
        else:
            row["paidOut"] += a.balance
    return {
        "currencies": [{"currency": c, **{k: _num(v) for k, v in r.items()}} for c, r in sorted(totals.items())],
        "openPayouts": Payout.objects.filter(status=PayoutStatus.REQUESTED).count(),
        "pendingAccounts": PayoutAccount.objects.filter(status=PayoutAccountStatus.PENDING).count(),
    }


# ── Notifications ────────────────────────────────────────────────────────────


def _notify_superusers(type_: str, tenant, obj, actor) -> None:
    from notifications.services import notify, platform_superusers

    try:
        data = {"business": tenant.name}
        if isinstance(obj, Payout):
            data.update(amount=wallet_money(obj.amount), currency=obj.currency)
        else:
            data.update(account=_account_label(obj))
        notify(recipients=platform_superusers(), type_=type_, actor=actor, data=data, link_id=obj.id,
               link_href="/console/platform/settlement")
    except Exception:
        logger.exception("Settlement notification %s failed", type_)


def _notify_owner(type_: str, tenant, actor, data: dict) -> None:
    from notifications.services import notify

    try:
        user = tenant.owner.user
        notify(recipients=[user], type_=type_, tenant=tenant, actor=actor, data={"business": tenant.name, **data},
               link_id=tenant.id, link_href="/console/settlement")
    except Exception:
        logger.exception("Settlement notification %s failed", type_)
