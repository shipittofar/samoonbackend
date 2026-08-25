from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from django.db import transaction


@dataclass(frozen=True)
class DomainEvent:
    name: str
    address_id: UUID
    user_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=datetime.utcnow)


def AddressCreated(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressCreated", address_id, user_id, payload or {})


def AddressUpdated(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressUpdated", address_id, user_id, payload or {})


def AddressDeleted(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressDeleted", address_id, user_id, payload or {})


def AddressRestored(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressRestored", address_id, user_id, payload or {})


def AddressDefaultChanged(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressDefaultChanged", address_id, user_id, payload or {})


def AddressVerificationChanged(address_id: UUID, user_id: UUID, payload: dict | None = None) -> DomainEvent:
    return DomainEvent("AddressVerificationChanged", address_id, user_id, payload or {})


EventHandler = Callable[[DomainEvent], None]


class AddressEventBus:
    _handlers: list[EventHandler] = []

    @classmethod
    def subscribe(cls, handler: EventHandler) -> None:
        cls._handlers.append(handler)

    @classmethod
    def publish(cls, event: DomainEvent) -> None:
        def _dispatch():
            for handler in cls._handlers:
                handler(event)

        transaction.on_commit(_dispatch)
