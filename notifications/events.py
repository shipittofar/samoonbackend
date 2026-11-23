"""One function per business event; called from the services that own the
event. Each decides who is told and with what details, then hands off to
services.notify (which waits for the transaction to commit)."""
from __future__ import annotations

import logging

from django.utils import timezone

from notifications.services import notify, platform_superusers, tenant_staff_with

logger = logging.getLogger(__name__)

ORDER_STAFF_PERMISSIONS = ("orders.view", "orders.manage")
RESERVATION_STAFF_PERMISSIONS = ("reservations.view", "reservations.manage")


def _safe(fn):
    """Events never raise into the caller."""

    def wrapper(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("Notification event %s failed", fn.__name__)

    wrapper.__name__ = fn.__name__
    return wrapper


def _person(user, fallback: str = "") -> str:
    if user is None:
        return fallback
    full = " ".join(p for p in (user.first_name, user.last_name) if p)
    return full or fallback or (user.phone_number or "")


def _when(dt) -> str:
    if not dt:
        return ""
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


# ── Orders ───────────────────────────────────────────────────────────────────


def _order_data(order) -> dict:
    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "branch": order.branch.name,
        "customer": _person(getattr(order, "customer", None), "—"),
        "status": order.status,
    }


@_safe
def order_created(order) -> None:
    tenant = order.branch.tenant
    notify(
        recipients=tenant_staff_with(tenant, ORDER_STAFF_PERMISSIONS, branch=order.branch),
        type_="order_created",
        tenant=tenant,
        branch=order.branch,
        actor=getattr(order, "customer", None),
        data=_order_data(order),
        link_id=order.id,
        link_href=f"/console/orders/{order.id}",
    )


@_safe
def order_status_changed(order, *, actor=None) -> None:
    """Tell the customer; a cancellation by the customer goes to the staff."""
    customer = getattr(order, "customer", None)
    if actor is not None and customer is not None and actor.id == customer.id:
        tenant = order.branch.tenant
        notify(
            recipients=tenant_staff_with(tenant, ORDER_STAFF_PERMISSIONS, branch=order.branch),
            type_="order_cancelled_by_customer",
            tenant=tenant,
            branch=order.branch,
            actor=actor,
            data=_order_data(order),
            link_id=order.id,
            link_href=f"/console/orders/{order.id}",
        )
        return
    if customer is None:
        return
    notify(
        recipients=[customer],
        type_="order_status_changed",
        tenant=None,
        actor=actor,
        data={**_order_data(order), "tenant_id": str(order.branch.tenant_id)},
        link_id=order.id,
        link_href=f"/order/{order.id}/track",
    )


# ── Reservations ─────────────────────────────────────────────────────────────


def _reservation_data(reservation) -> dict:
    return {
        "reservation_id": str(reservation.id),
        "branch": reservation.branch.name,
        "customer": reservation.guest_name or _person(getattr(reservation, "customer", None), "—"),
        "party_size": reservation.party_size,
        "when": _when(reservation.reserved_at),
        "status": reservation.status,
    }


@_safe
def reservation_created(reservation) -> None:
    tenant = reservation.branch.tenant
    notify(
        recipients=tenant_staff_with(tenant, RESERVATION_STAFF_PERMISSIONS, branch=reservation.branch),
        type_="reservation_created",
        tenant=tenant,
        branch=reservation.branch,
        actor=getattr(reservation, "customer", None),
        data=_reservation_data(reservation),
        link_id=reservation.id,
        link_href=f"/console/reservations/{reservation.id}",
    )


@_safe
def reservation_status_changed(reservation, *, actor=None) -> None:
    customer = getattr(reservation, "customer", None)
    if actor is not None and customer is not None and actor.id == customer.id:
        tenant = reservation.branch.tenant
        notify(
            recipients=tenant_staff_with(tenant, RESERVATION_STAFF_PERMISSIONS, branch=reservation.branch),
            type_="reservation_cancelled_by_customer",
            tenant=tenant,
            branch=reservation.branch,
            actor=actor,
            data=_reservation_data(reservation),
            link_id=reservation.id,
            link_href=f"/console/reservations/{reservation.id}",
        )
        return
    type_ = {"confirmed": "reservation_confirmed", "cancelled": "reservation_cancelled"}.get(reservation.status)
    if customer is None or type_ is None:
        return
    notify(
        recipients=[customer],
        type_=type_,
        actor=actor,
        data=_reservation_data(reservation),
        link_id=reservation.id,
        link_href="/dashboard/reservations",
    )


# ── Business registration ────────────────────────────────────────────────────


@_safe
def business_request_created(item) -> None:
    notify(
        recipients=platform_superusers(),
        type_="business_request_created",
        actor=item.user,
        data={"request_id": str(item.id), "business": item.name, "applicant": _person(item.user, "—")},
        link_id=item.id,
        link_href="/console/platform/requests",
    )


@_safe
def business_request_decided(item, *, actor=None) -> None:
    approved = item.status == "approved"
    tenant = getattr(item, "tenant", None) if approved else None
    notify(
        recipients=[item.user],
        type_="business_request_approved" if approved else "business_request_rejected",
        tenant=None,
        actor=actor,
        data={
            "request_id": str(item.id),
            "business": item.name,
            "reason": getattr(item, "rejection_reason", "") or "",
            **({"tenant_id": str(tenant.id)} if tenant else {}),
        },
        link_id=getattr(tenant, "id", "") or item.id,
        link_href="/console" if approved else "/business/register",
    )


# ── Staff ────────────────────────────────────────────────────────────────────


@_safe
def staff_membership_changed(membership, type_: str, *, actor=None) -> None:
    """type_: staff_created | staff_suspended | staff_removed."""
    tenant = membership.tenant
    notify(
        recipients=[membership.user],
        type_=type_,
        tenant=tenant if type_ == "staff_created" else None,
        actor=actor,
        data={"business": tenant.name, "tenant_id": str(tenant.id)},
        link_id=tenant.id,
        link_href="/console" if type_ == "staff_created" else "",
    )


# ── Account security ─────────────────────────────────────────────────────────


@_safe
def password_changed(user) -> None:
    notify(recipients=[user], type_="password_changed", actor=user, data={})


# ── Wallet ───────────────────────────────────────────────────────────────────


def _money(value) -> str:
    """1234.5000 -> "1,234.5"; 200000.0000 -> "200,000"."""
    from decimal import Decimal

    d = Decimal(value).normalize()
    text = f"{d:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@_safe
def wallet_transaction(tx) -> None:
    """Tell the customer whose wallet a ledger transaction touched."""
    type_ = {
        "order_payment": "wallet_payment",
        "order_refund": "wallet_refund",
        "topup": "wallet_topup",
        "adjustment": "wallet_adjustment",
    }.get(tx.kind)
    if type_ is None:
        return
    for entry in tx.entries.select_related("account__user"):
        account = entry.account
        if account.kind != "customer" or account.user is None:
            continue
        order = tx.order
        notify(
            recipients=[account.user],
            type_=type_,
            actor=tx.created_by if tx.created_by_id != account.user_id else None,
            data={
                "amount": _money(abs(entry.amount)),
                "signed_amount": ("+" if entry.amount > 0 else "−") + _money(abs(entry.amount)),
                "currency": tx.currency,
                "balance": _money(entry.balance_after),
                "reason": tx.description if tx.kind == "adjustment" else "",
                "order_number": getattr(order, "order_number", "") or "",
                "transaction_id": str(tx.id),
            },
            link_id=getattr(order, "id", "") or tx.id,
            link_href=f"/order/{order.id}/track" if order else "/dashboard/wallet",
        )
