"""Creating, serializing and pushing notifications.

Everything here runs after the surrounding transaction commits
(``transaction.on_commit``) and swallows its own errors: a notification
problem must never break the order, reservation or approval that caused it.
"""
from __future__ import annotations

import logging
from typing import Iterable

from asgiref.sync import async_to_sync
from django.db import transaction

from notifications import catalog
from notifications.models import PRIORITY_RANK, Notification, NotificationPreference, NotificationStatus

logger = logging.getLogger(__name__)


def user_group_name(user_id) -> str:
    """Channels group of one user's notification sockets."""
    return f"notifications.user.{user_id}"


# ── Serialization (shared by the API and the websocket) ─────────────────────


def _actor_name(user) -> str:
    if user is None:
        return ""
    full = " ".join(p for p in (user.first_name, user.last_name) if p)
    return full or (user.phone_number or "") or (user.email or "")


def serialize(notification: Notification, language: str = catalog.DEFAULT_LANGUAGE) -> dict:
    """The frontend's RichNotification shape, text in ``language``."""
    title, message = catalog.render(notification.type, notification.data, language)
    spec = catalog.TYPES.get(notification.type)
    out = {
        "id": str(notification.id),
        "type": notification.type,
        "category": notification.category,
        "priority": notification.priority,
        "status": notification.status,
        "title": title,
        "message": message,
        "scope": {
            "tenantId": str(notification.tenant_id) if notification.tenant_id else "",
            **({"branchId": str(notification.branch_id)} if notification.branch_id else {}),
        },
        "channels": list(spec.channels) if spec else ["in_app"],
        "data": notification.data or {},
        "created_at": notification.created_at.isoformat(),
    }
    if notification.actor_id or notification.actor_name:
        out["actor"] = {
            "id": str(notification.actor_id) if notification.actor_id else "",
            "name": notification.actor_name,
            "roles": [],
        }
    if notification.link_href:
        out["deepLink"] = {"type": notification.link_type, "id": notification.link_id, "href": notification.link_href}
    if notification.read_at:
        out["readAt"] = notification.read_at.isoformat()
    if notification.archived_at:
        out["archivedAt"] = notification.archived_at.isoformat()
    return out


# ── Preferences ──────────────────────────────────────────────────────────────


def wants(user_id, *, tenant_id, category: str, priority: str) -> bool:
    """False when the user turned this category off (or raised its minimum
    priority above this one) for this business — or for personal ones."""
    pref = NotificationPreference.objects.filter(user_id=user_id, tenant_id=tenant_id, category=category).first()
    if pref is None:
        return True
    if not pref.enabled or not (pref.channels or {}).get("in_app", True):
        return False
    return PRIORITY_RANK.get(priority, 1) >= PRIORITY_RANK.get(pref.min_priority, 0)


# ── Recipients ───────────────────────────────────────────────────────────────


def tenant_staff_with(tenant, permission_slugs: Iterable[str], *, branch=None) -> list:
    """The owner plus active staff who hold any of ``permission_slugs`` on
    this business (and branch, when given)."""
    from access.models import StaffMembership, StaffMembershipStatus
    from access.selectors.permission_dal import permission_selector

    users = {tenant.owner.user_id: tenant.owner.user}
    memberships = StaffMembership.objects.filter(tenant=tenant, status=StaffMembershipStatus.ACTIVE).select_related("user")
    for membership in memberships:
        user = membership.user
        if user.id in users or not user.is_active:
            continue
        try:
            allowed = permission_selector.user_has_permissions(
                user_id=user.id,
                tenant_id=tenant.id,
                branch_id=getattr(branch, "id", None),
                permission_slugs=tuple(permission_slugs),
                require_all=False,
            )
        except Exception:
            logger.exception("Could not check notification permissions user_id=%s", user.id)
            allowed = False
        if allowed:
            users[user.id] = user
    return [u for u in users.values() if u.is_active]


def platform_superusers() -> list:
    from accounts.models import User

    return list(User.objects.filter(is_superuser=True, is_active=True, is_deleted=False))


# ── Creating + pushing ───────────────────────────────────────────────────────


def _push(notification: Notification) -> None:
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        return
    unread = Notification.objects.filter(recipient_id=notification.recipient_id, status=NotificationStatus.UNREAD).count()
    try:
        async_to_sync(layer.group_send)(
            user_group_name(notification.recipient_id),
            {"type": "notification.event", "notification_id": str(notification.id), "unread": unread},
        )
    except Exception:
        logger.exception("Failed to push notification %s", notification.id)


def _create(*, recipients, type_: str, tenant=None, branch=None, actor=None, data=None, link_id="", link_href="") -> list:
    spec = catalog.TYPES[type_]
    created = []
    for user in recipients:
        if actor is not None and getattr(actor, "id", None) == user.id and type_ not in {"password_changed"}:
            continue  # nobody needs to be told about what they just did themselves
        if not wants(user.id, tenant_id=getattr(tenant, "id", None), category=spec.category, priority=spec.priority):
            continue
        created.append(
            Notification.objects.create(
                recipient=user,
                tenant=tenant,
                branch=branch,
                type=type_,
                category=spec.category,
                priority=spec.priority,
                actor=actor if getattr(actor, "pk", None) else None,
                actor_name=_actor_name(actor),
                data=data or {},
                link_type=spec.link_type,
                link_id=str(link_id or ""),
                link_href=link_href or "",
            )
        )
    for notification in created:
        _push(notification)
    return created


def notify(*, recipients, type_: str, **kwargs) -> None:
    """Create ``type_`` notifications for ``recipients`` once the current
    transaction commits (immediately when there is none)."""
    recipients = list(recipients)
    if not recipients:
        return

    from notifications.live import push_changes, topics_for_type

    actor = kwargs.get("actor")
    push_changes([*(u.id for u in recipients), getattr(actor, "id", None)], topics_for_type(type_))

    def run():
        try:
            _create(recipients=recipients, type_=type_, **kwargs)
        except Exception:
            logger.exception("Failed to create %s notifications", type_)

    transaction.on_commit(run)
