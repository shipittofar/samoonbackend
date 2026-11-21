from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from access.authorization.platform import is_platform_superuser
from orders.models import Order


class OrderStatusConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        self.public_id = self.scope["url_route"]["kwargs"]["public_id"]
        user = self.scope["user"]

        if user.is_anonymous:
            await self.close(code=4001)  # Unauthorized
            return

        order = await self._get_order()
        if order is None:
            await self.close(code=4004)  # Not found
            return

        if not await self._can_access(order, user):
            await self.close(code=4003)  # Forbidden
            return

        self.group_name = f"order_status_{self.public_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send_json({
            "type": "connection_established",
            "status": order.status,
            "public_id": str(order.id),
        })

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def order_status_update(self, event):
        await self.send_json(event["data"])

    @database_sync_to_async
    def _get_order(self):
        try:
            return Order.objects.select_related(
                "customer", "branch", "branch__tenant"
            ).get(pk=self.public_id)
        except Order.DoesNotExist:
            return None

    @database_sync_to_async
    def _can_access(self, order, user) -> bool:
        return order.customer_id == user.id or is_platform_superuser(user)