"""Personal notification socket: /ws/notifications/?token=<access>&lang=fa

One group per user. On every new notification the server sends
{"type": "notification.new", "data": <RichNotification>, "unreadCount": n}
with the text in the socket's language. Missed events while disconnected
are recovered by refetching over HTTP when the socket reconnects.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from notifications import catalog
from notifications.services import serialize, user_group_name

logger = logging.getLogger(__name__)

CLOSE_UNAUTHORIZED = 4001


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        query = parse_qs((self.scope.get("query_string") or b"").decode())
        self.language = catalog.pick_language((query.get("lang") or [""])[0])
        self.user_id = user.id
        self.group_name = user_group_name(user.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection_established", "data": {"unreadCount": await self._unread()}})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Only keep-alive is accepted; group membership is server-assigned.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong", "data": content.get("data")})

    async def notification_event(self, event):
        payload = await self._payload(event["notification_id"])
        if payload is None:
            return
        await self.send_json({"type": "notification.new", "data": payload, "unreadCount": event.get("unread", 0)})

    async def data_changed(self, event):
        # Topic names only; the page refetches through the API (notifications.live).
        await self.send_json({"type": "data.changed", "data": {"topics": event.get("topics", [])}})

    @database_sync_to_async
    def _payload(self, notification_id):
        from notifications.models import Notification

        n = Notification.objects.filter(id=notification_id, recipient_id=self.user_id).first()
        return serialize(n, self.language) if n else None

    @database_sync_to_async
    def _unread(self):
        from notifications.models import Notification, NotificationStatus

        return Notification.objects.filter(recipient_id=self.user_id, status=NotificationStatus.UNREAD).count()
