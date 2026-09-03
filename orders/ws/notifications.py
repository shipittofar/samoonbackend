import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from core.ws.publisher import ORDER_CHANGED, schedule_console_event_on_commit
from orders.models import Order

logger = logging.getLogger(__name__)


def notify_order_status_change(order: Order) -> None:
    """Existing per-order customer websocket. Do not rename this event type."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("Order status event not published: no channel layer")
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f"order_status_{order.id}",
            {
                "type": "order.status.update",
                "data": {
                    "id": str(order.id),
                    "status": order.status,
                    "updated_at": order.updated_at.isoformat(),
                },
            },
        )
    except Exception:
        logger.exception(
            "Failed to publish order status websocket event order_id=%s",
            order.id,
        )


def schedule_console_order_changed(order: Order) -> None:
    """Console workspace signal. Emitted after commit from the orders BLL only."""
    schedule_console_event_on_commit(
        tenant_id=order.branch.tenant_id,
        branch_id=order.branch_id,
        event_type=ORDER_CHANGED,
        data={
            "tenant_id": str(order.branch.tenant_id),
            "branch_id": str(order.branch_id),
            "order_id": str(order.id),
            "status": order.status,
        },
    )
