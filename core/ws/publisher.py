from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from core.ws.groups import console_group_name

logger = logging.getLogger(__name__)

ORDER_CHANGED = "order.changed"
RESERVATION_CHANGED = "reservation.changed"


def publish_console_event(
    *,
    tenant_id: UUID | str,
    branch_id: UUID | str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """
    Publish a Console workspace event to the tenant+branch Channels group.

    The payload is a synchronization signal. Clients must refetch
    authoritative counts over HTTP rather than incrementing locally.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning(
            "Console event not published: no channel layer configured (type=%s)",
            event_type,
        )
        return

    group = console_group_name(tenant_id=tenant_id, branch_id=branch_id)
    try:
        async_to_sync(channel_layer.group_send)(
            group,
            {
                "type": "console.event",
                "payload": {
                    "type": event_type,
                    "data": data,
                },
            },
        )
    except Exception:
        logger.exception(
            "Failed to publish console websocket event type=%s tenant_id=%s branch_id=%s",
            event_type,
            tenant_id,
            branch_id,
        )


def schedule_console_event_on_commit(
    *,
    tenant_id: UUID | str,
    branch_id: UUID | str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Publish only after the surrounding database transaction commits."""
    transaction.on_commit(
        lambda: publish_console_event(
            tenant_id=tenant_id,
            branch_id=branch_id,
            event_type=event_type,
            data=data,
        )
    )
