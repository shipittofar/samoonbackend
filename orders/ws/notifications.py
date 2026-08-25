from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from orders.models import Order


def notify_order_status_change(order: Order) -> None:
    channel_layer = get_channel_layer()
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
