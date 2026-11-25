"""Silent "your data changed" pushes over the personal notification socket.

Separate from notifications: sent even when the user muted a category or did
the action themselves (another tab), never stored, and carries only topic
names. The page refetches those over the normal, permission-checked API.

Topics: session (account type, businesses, roles), orders, reservations,
wallet, settlement, business_requests.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)

_PREFIX_TOPICS = (
    ("order_", ("orders",)),
    ("reservation_", ("reservations",)),
    ("wallet_", ("wallet",)),
    ("settlement_", ("settlement",)),
    ("business_request_", ("session", "business_requests")),
    ("staff_", ("session",)),
)


def topics_for_type(type_: str) -> tuple[str, ...]:
    for prefix, topics in _PREFIX_TOPICS:
        if type_.startswith(prefix):
            return topics
    return ()


def push_changes(user_ids, topics) -> None:
    """After commit, tell these users' open pages which data to refetch."""
    ids = {str(u) for u in user_ids if u}
    topics = sorted(set(topics))
    if ids and topics:
        transaction.on_commit(lambda: _send(ids, topics), robust=True)


def _send(user_ids, topics) -> None:
    from channels.layers import get_channel_layer

    from notifications.services import user_group_name

    layer = get_channel_layer()
    if layer is None:
        return
    for user_id in user_ids:
        try:
            async_to_sync(layer.group_send)(user_group_name(user_id), {"type": "data.changed", "topics": topics})
        except Exception:
            logger.exception("Failed to push data change to user %s", user_id)


def _session_changed(sender, instance, **kwargs) -> None:
    if kwargs.get("raw"):
        return
    try:
        name = sender.__name__
        if name in ("Owner", "StaffMembership"):
            user_id = instance.user_id
        elif name == "Tenant":
            user_id = instance.owner.user_id
        else:  # StaffAssignment, PermissionOverride
            user_id = instance.membership.user_id
        push_changes([user_id], ["session"])
    except Exception:
        logger.exception("Could not announce a session change (%s)", sender.__name__)


def connect_signals() -> None:
    """What decides a user's account type, businesses and permissions."""
    from access.models.membership import StaffAssignment, StaffMembership
    from access.models.permission_override import PermissionOverride
    from tenants.models import Owner, Tenant

    for model in (Owner, Tenant, StaffMembership, StaffAssignment, PermissionOverride):
        uid = f"live-session-{model.__name__}"
        post_save.connect(_session_changed, sender=model, dispatch_uid=f"{uid}-save")
        post_delete.connect(_session_changed, sender=model, dispatch_uid=f"{uid}-delete")
