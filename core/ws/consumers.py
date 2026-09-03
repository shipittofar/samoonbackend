from __future__ import annotations

import logging
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from access.authorization.console_workspace import (
    CONSOLE_WORKSPACE_PERMISSIONS,
    user_has_console_permissions,
)
from core.ws.groups import console_group_name
from tenants.models import Branch

logger = logging.getLogger(__name__)

CLOSE_UNAUTHORIZED = 4001
CLOSE_FORBIDDEN = 4003
CLOSE_NOT_FOUND = 4004


class ConsoleConsumer(AsyncJsonWebsocketConsumer):
    """
    Authenticated Console workspace socket, scoped to one authorized branch.

    Clients reconnect by authenticating again and rejoining this group.
    Missed events are reconciled by refetching authoritative HTTP counts.
    """

    async def connect(self):
        user = self.scope.get("user")
        raw_branch_id = self.scope["url_route"]["kwargs"]["branch_id"]

        if user is None or isinstance(user, AnonymousUser) or user.is_anonymous:
            logger.info("Console websocket authentication failed (anonymous)")
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        try:
            branch_id = UUID(str(raw_branch_id))
        except (TypeError, ValueError):
            logger.info("Console websocket rejected invalid branch_id")
            await self.close(code=CLOSE_NOT_FOUND)
            return

        branch = await self._get_branch(branch_id)
        if branch is None:
            logger.info(
                "Console websocket branch not found user_id=%s",
                user.id,
            )
            await self.close(code=CLOSE_NOT_FOUND)
            return

        allowed = await self._authorize(user, branch)
        if not allowed:
            logger.info(
                "Console websocket authorization failed user_id=%s branch_id=%s tenant_id=%s",
                user.id,
                branch.id,
                branch.tenant_id,
            )
            await self.close(code=CLOSE_FORBIDDEN)
            return

        self.tenant_id = branch.tenant_id
        self.branch_id = branch.id
        self.group_name = console_group_name(
            tenant_id=self.tenant_id,
            branch_id=self.branch_id,
        )
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "Console websocket connected user_id=%s tenant_id=%s branch_id=%s",
            user.id,
            self.tenant_id,
            self.branch_id,
        )
        await self.send_json(
            {
                "type": "connection_established",
                "data": {
                    "tenant_id": str(self.tenant_id),
                    "branch_id": str(self.branch_id),
                },
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(
                "Console websocket disconnected user_id=%s tenant_id=%s branch_id=%s code=%s",
                getattr(self.scope.get("user"), "id", None),
                getattr(self, "tenant_id", None),
                getattr(self, "branch_id", None),
                close_code,
            )

    async def receive_json(self, content, **kwargs):
        # Group membership is server-assigned. Ignore client join/scope messages.
        logger.info(
            "Console websocket ignored client message user_id=%s keys=%s",
            getattr(self.scope.get("user"), "id", None),
            sorted(content.keys()) if isinstance(content, dict) else "invalid",
        )

    async def console_event(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _get_branch(self, branch_id: UUID):
        return (
            Branch.objects.select_related("tenant", "tenant__owner")
            .filter(pk=branch_id)
            .first()
        )

    @database_sync_to_async
    def _authorize(self, user, branch) -> bool:
        return user_has_console_permissions(
            user=user,
            tenant_id=branch.tenant_id,
            branch_id=branch.id,
            permission_slugs=CONSOLE_WORKSPACE_PERMISSIONS,
        )
