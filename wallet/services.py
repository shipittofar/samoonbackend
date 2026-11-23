"""The only code that moves wallet money.

``post()`` is the single write path: it locks the accounts involved (in a
fixed order, so two transfers can never deadlock), refuses to take a
non-negative account below zero, checks the amounts balance, writes the
entries and updates the cached balances — all in one database transaction.
Everything else (order payment, refund, adjustment, top-up) builds on it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from wallet.models import AccountKind, LedgerEntry, LedgerTransaction, TransactionKind, WalletAccount

logger = logging.getLogger(__name__)

LIMITS_KEY = "wallet.limits"
QUANT = Decimal("0.0001")


class InsufficientFunds(APIException):
    status_code = 400
    default_code = "wallet_insufficient_funds"
    default_detail = "Not enough balance in the wallet."


class WalletFrozen(APIException):
    status_code = 403
    default_code = "wallet_frozen"
    default_detail = "This wallet is frozen."


class LimitExceeded(APIException):
    status_code = 400
    default_code = "wallet_limit_exceeded"
    default_detail = "This exceeds the wallet limit."


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(QUANT)
    except (InvalidOperation, TypeError):
        raise ValidationError({"amount": "Not a number."})
    return amount


# ── Accounts ─────────────────────────────────────────────────────────────────


def customer_account(user, currency: str) -> WalletAccount:
    account, _ = WalletAccount.objects.get_or_create(kind=AccountKind.CUSTOMER, user=user, currency=currency.upper())
    return account


def business_account(tenant, currency: str) -> WalletAccount:
    account, _ = WalletAccount.objects.get_or_create(
        kind=AccountKind.BUSINESS, tenant=tenant, currency=currency.upper()
    )
    return account


def system_account(kind: str, currency: str) -> WalletAccount:
    account, _ = WalletAccount.objects.get_or_create(
        kind=kind, user=None, tenant=None, currency=currency.upper(), defaults={"allow_negative": True}
    )
    return account


def balance_of(user, currency: str) -> Decimal:
    account = WalletAccount.objects.filter(kind=AccountKind.CUSTOMER, user=user, currency=currency.upper()).first()
    return account.balance if account else Decimal("0")


# ── Limits (platform settings) ───────────────────────────────────────────────


def limits() -> dict:
    """{"per_transaction": {"IRT": "50000000"}, "daily_spend": {...}, "daily_topup": {...}}"""
    from platform_settings.models import PlatformSetting

    row = PlatformSetting.objects.filter(key=LIMITS_KEY).first()
    return row.value if row and isinstance(row.value, dict) else {}


def _limit(name: str, currency: str) -> Decimal | None:
    raw = (limits().get(name) or {}).get(currency)
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _check_limits(account: WalletAccount, amount: Decimal, *, limit_name: str, kinds: list[str]) -> None:
    per_tx = _limit("per_transaction", account.currency)
    if per_tx is not None and amount > per_tx:
        raise LimitExceeded(f"More than the {per_tx} {account.currency} per-transaction limit.")
    daily = _limit(limit_name, account.currency)
    if daily is None:
        return
    since = timezone.now() - timezone.timedelta(days=1)
    used = (
        LedgerEntry.objects.filter(account=account, created_at__gte=since, transaction__kind__in=kinds)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    if abs(used) + amount > daily:
        raise LimitExceeded(f"More than the {daily} {account.currency} daily limit.")


# ── Posting ──────────────────────────────────────────────────────────────────


@dataclass
class Leg:
    account: WalletAccount
    amount: Decimal  # + into, - out of


def post(
    *,
    kind: str,
    currency: str,
    legs: list[Leg],
    idempotency_key: str,
    order=None,
    reverses=None,
    description: str = "",
    created_by=None,
    metadata: dict | None = None,
) -> LedgerTransaction:
    """Write one balanced transaction, or return the existing one for this key."""
    currency = currency.upper()
    existing = LedgerTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if not legs or sum((leg.amount for leg in legs), Decimal("0")) != 0:
        raise ValueError("A ledger transaction must balance to zero.")
    if any(leg.account.currency != currency for leg in legs):
        raise ValueError("All legs must be in the transaction currency.")

    try:
        with transaction.atomic():
            ids = sorted({leg.account.id for leg in legs}, key=str)
            locked = {a.id: a for a in WalletAccount.objects.select_for_update().filter(id__in=ids).order_by("id")}
            tx = LedgerTransaction.objects.create(
                kind=kind,
                currency=currency,
                idempotency_key=idempotency_key,
                order=order,
                reverses=reverses,
                description=description[:300],
                created_by=created_by if getattr(created_by, "pk", None) else None,
                metadata=metadata or {},
            )
            for leg in legs:
                account = locked[leg.account.id]
                if leg.amount < 0 and account.is_frozen:
                    raise WalletFrozen()
                new_balance = account.balance + leg.amount
                if new_balance < 0 and not account.allow_negative:
                    raise InsufficientFunds()
                account.balance = new_balance
                account.save(update_fields=["balance", "updated_at"])
                LedgerEntry.objects.create(transaction=tx, account=account, amount=leg.amount, balance_after=new_balance)
    except IntegrityError:
        # A concurrent request with the same key won the race.
        existing = LedgerTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing is None:
            raise
        return existing

    transaction.on_commit(lambda: _notify(tx))
    return tx


def _notify(tx: LedgerTransaction) -> None:
    try:
        from notifications import events

        events.wallet_transaction(tx)
    except Exception:
        logger.exception("Wallet notification failed for %s", tx.id)


# ── Operations ───────────────────────────────────────────────────────────────


def pay_order(order, *, customer) -> LedgerTransaction:
    """Debit the customer's wallet (order currency) and credit the business.
    Call inside the order's database transaction; insufficient balance raises
    and rolls the order back."""
    currency = (order.currency or "").upper() or "IRT"
    amount = _amount(order.total)
    if amount <= 0:
        raise ValidationError({"payment_method": "Nothing to pay."})
    payer = customer_account(customer, currency)
    _check_limits(payer, amount, limit_name="daily_spend", kinds=[TransactionKind.ORDER_PAYMENT])
    payee = business_account(order.branch.tenant, currency)
    tx = post(
        kind=TransactionKind.ORDER_PAYMENT,
        currency=currency,
        legs=[Leg(payer, -amount), Leg(payee, amount)],
        idempotency_key=f"order-payment:{order.id}",
        order=order,
        description=f"Order {order.order_number}",
        created_by=customer,
    )
    from orders.models import PaymentStatus

    if order.payment_status != PaymentStatus.PAID:
        order.payment_status = PaymentStatus.PAID
        order.save(update_fields=["payment_status", "updated_at"])
    return tx


def refund_order(order, *, actor=None) -> LedgerTransaction | None:
    """Return a wallet-paid order's money to the customer (once)."""
    payment = LedgerTransaction.objects.filter(order=order, kind=TransactionKind.ORDER_PAYMENT).first()
    if payment is None or hasattr(payment, "reversed_by"):
        return None
    legs = [Leg(entry.account, -entry.amount) for entry in payment.entries.select_related("account")]
    tx = post(
        kind=TransactionKind.ORDER_REFUND,
        currency=payment.currency,
        legs=legs,
        idempotency_key=f"order-refund:{order.id}",
        order=order,
        reverses=payment,
        description=f"Refund of order {order.order_number}",
        created_by=actor,
    )
    from orders.models import PaymentStatus

    order.payment_status = PaymentStatus.REFUNDED
    order.save(update_fields=["payment_status", "updated_at"])
    return tx


def adjust(*, user, currency: str, amount, reason: str, actor, idempotency_key: str) -> LedgerTransaction:
    """Superuser correction: + credits the customer, - debits (never below zero)."""
    value = _amount(amount)
    if value == 0:
        raise ValidationError({"amount": "Must not be zero."})
    if not (reason or "").strip():
        raise ValidationError({"reason": "A reason is required."})
    customer = customer_account(user, currency)
    system = system_account(AccountKind.SYSTEM_ADJUSTMENT, currency)
    return post(
        kind=TransactionKind.ADJUSTMENT,
        currency=currency,
        legs=[Leg(customer, value), Leg(system, -value)],
        idempotency_key=idempotency_key,
        description=reason.strip(),
        created_by=actor,
    )


def credit_topup(
    *, user, currency: str, amount, reference: str, metadata: dict | None = None, enforce_limits: bool = True
) -> LedgerTransaction:
    """Money received from a gateway (phase E): credit the customer once per reference."""
    value = _amount(amount)
    if value <= 0:
        raise ValidationError({"amount": "Must be positive."})
    customer = customer_account(user, currency)
    if enforce_limits:  # off once the money is already received (checked at start)
        _check_limits(customer, value, limit_name="daily_topup", kinds=[TransactionKind.TOPUP])
    system = system_account(AccountKind.SYSTEM_TOPUP, currency)
    return post(
        kind=TransactionKind.TOPUP,
        currency=currency,
        legs=[Leg(customer, value), Leg(system, -value)],
        idempotency_key=f"topup:{reference}",
        description=f"Top-up {reference}",
        created_by=user,
        metadata=metadata,
    )


# ── Health ───────────────────────────────────────────────────────────────────


def health() -> dict:
    """Ledger invariants: every transaction balances, every cached balance
    equals the sum of its entries, nothing non-negative is below zero."""
    problems: list[str] = []
    unbalanced = (
        LedgerEntry.objects.values("transaction_id").annotate(total=Sum("amount")).exclude(total=0)
    )
    for row in unbalanced[:50]:
        problems.append(f"transaction {row['transaction_id']} does not balance ({row['total']})")
    sums = dict(LedgerEntry.objects.values("account_id").annotate(total=Sum("amount")).values_list("account_id", "total"))
    accounts = WalletAccount.objects.all()
    for account in accounts:
        expected = sums.get(account.id) or Decimal("0")
        if account.balance != expected:
            problems.append(f"account {account} balance {account.balance} != entries {expected}")
        if account.balance < 0 and not account.allow_negative:
            problems.append(f"account {account} is negative")
    totals: dict[str, Decimal] = {}
    for account in accounts:
        totals[account.currency] = totals.get(account.currency, Decimal("0")) + account.balance
    for currency, total in totals.items():
        if total != 0:
            problems.append(f"currency {currency}: all balances sum to {total}, not 0")
    return {
        "ok": not problems,
        "problems": problems,
        "accounts": accounts.count(),
        "transactions": LedgerTransaction.objects.count(),
    }
