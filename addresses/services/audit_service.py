from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from addresses.models import AddressAuditLog


def _json_safe(value: Any) -> Any:
    """Convert audit payload values to JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


class AddressAuditService:
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_RESTORE = "restore"
    ACTION_SET_DEFAULT = "set_default"
    ACTION_VERIFICATION_CHANGE = "verification_change"

    @staticmethod
    def log(
        *,
        address_id: UUID,
        user_id: UUID,
        actor_id: UUID | None,
        action: str,
        changed_fields: dict[str, Any] | None = None,
    ) -> AddressAuditLog:
        safe_fields = _json_safe(changed_fields or {})
        return AddressAuditLog.objects.create(
            address_id=address_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            changed_fields=safe_fields,
        )
