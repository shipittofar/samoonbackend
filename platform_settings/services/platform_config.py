"""Platform-level overrides of Platform Configuration fields.

The field catalogue (ids, types, defaults, validation) lives in the frontend
registry (src/config). The backend stores only the values a superuser changed,
one PlatformSetting row per field (key ``config:<fieldId>``), and a change log
(PlatformSettingChange). The frontend loads them before rendering, so every
visitor — and the server-side render — sees the same settings.

Platform configuration never holds secrets (frontend rule: 'secret' and
'password' fields are not persisted here), so the overrides are public.
"""
from __future__ import annotations

import json
import re

from django.db import transaction
from rest_framework.exceptions import ValidationError

from platform_settings.models import PlatformSetting, PlatformSettingChange, TenantConfigOverride

PREFIX = "config:"
FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
MAX_FIELD_ID = 100 - len(PREFIX)
MAX_CHANGES = 200
MAX_VALUE_BYTES = 64 * 1024
MAX_REASON = 500


def get_overrides() -> dict:
    """{fieldId: value} for every field a superuser has overridden."""
    rows = PlatformSetting.objects.filter(key__startswith=PREFIX).values_list("key", "value")
    return {key[len(PREFIX):]: value for key, value in rows}


def _clean_changes(data) -> tuple[list[tuple[str, object, bool]], str]:
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object.")
    changes = data.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValidationError({"changes": "A non-empty list is required."})
    if len(changes) > MAX_CHANGES:
        raise ValidationError({"changes": f"At most {MAX_CHANGES} changes per request."})
    reason = data.get("reason") or ""
    if not isinstance(reason, str):
        raise ValidationError({"reason": "Must be text."})

    cleaned = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValidationError({"changes": "Each change must be an object."})
        field_id = change.get("fieldId")
        if not isinstance(field_id, str) or len(field_id) > MAX_FIELD_ID or not FIELD_ID_RE.match(field_id):
            raise ValidationError({"changes": f"Invalid fieldId: {field_id!r}"})
        if field_id in seen:
            raise ValidationError({"changes": f"{field_id} appears more than once."})
        seen.add(field_id)
        reset = change.get("reset") is True
        if not reset and "value" not in change:
            raise ValidationError({"changes": f"{field_id}: give a value, or reset: true."})
        value = None if reset else change["value"]
        if len(json.dumps(value)) > MAX_VALUE_BYTES:
            raise ValidationError({"changes": f"{field_id}: value is too large."})
        cleaned.append((field_id, value, reset))
    return cleaned, reason.strip()[:MAX_REASON]


def save_overrides(*, user, data) -> dict:
    """Apply a batch of overrides atomically (all or nothing) and log each one.

    ``{"changes": [{"fieldId": "...", "value": ...} | {"fieldId": "...", "reset": true}],
       "reason": "..."}``
    """
    changes, reason = _clean_changes(data)
    actor = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        keys = [PREFIX + field_id for field_id, _, _ in changes]
        existing = {row.key: row for row in PlatformSetting.objects.select_for_update().filter(key__in=keys)}
        log = []
        for field_id, value, reset in changes:
            key = PREFIX + field_id
            row = existing.get(key)
            previous = row.value if row else None
            if reset:
                if row is None:
                    continue
                row.delete()
            else:
                if row is not None and row.value == value:
                    continue
                if row is None:
                    row = PlatformSetting(key=key)
                row.value = value
                row.updated_by = actor
                row.save()
            log.append(
                PlatformSettingChange(
                    key=key, previous_value=previous, new_value=value, reason=reason, changed_by=actor
                )
            )
        PlatformSettingChange.objects.bulk_create(log)
    return get_overrides()


def get_tenant_overrides(tenant_id) -> dict:
    """{fieldId: value} a business set for its tenant-level fields."""
    return dict(TenantConfigOverride.objects.filter(tenant_id=tenant_id).values_list("field_id", "value"))


def save_tenant_overrides(*, user, tenant, data) -> dict:
    """Same request shape and rules as save_overrides, for one business."""
    changes, reason = _clean_changes(data)
    actor = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        field_ids = [field_id for field_id, _, _ in changes]
        existing = {
            row.field_id: row
            for row in TenantConfigOverride.objects.select_for_update().filter(tenant=tenant, field_id__in=field_ids)
        }
        log = []
        for field_id, value, reset in changes:
            row = existing.get(field_id)
            previous = row.value if row else None
            if reset:
                if row is None:
                    continue
                row.delete()
            else:
                if row is not None and row.value == value:
                    continue
                if row is None:
                    row = TenantConfigOverride(tenant=tenant, field_id=field_id)
                row.value = value
                row.updated_by = actor
                row.save()
            log.append(
                PlatformSettingChange(
                    key=PREFIX + field_id,
                    tenant=tenant,
                    previous_value=previous,
                    new_value=value,
                    reason=reason,
                    changed_by=actor,
                )
            )
        PlatformSettingChange.objects.bulk_create(log)
    return get_tenant_overrides(tenant.id)


def history(*, field_id: str | None = None, limit: int = 100, tenant_id=None) -> list[dict]:
    """Platform-wide changes, or one business's changes when tenant_id is given."""
    qs = PlatformSettingChange.objects.filter(key__startswith=PREFIX).select_related("changed_by")
    qs = qs.filter(tenant_id=tenant_id) if tenant_id else qs.filter(tenant__isnull=True)
    if field_id:
        qs = qs.filter(key=PREFIX + field_id)
    out = []
    for change in qs[: max(1, min(limit, 500))]:
        who = change.changed_by
        name = ""
        if who is not None:
            full = " ".join(part for part in (who.first_name, who.last_name) if part)
            name = full or who.phone_number or who.email or ""
        out.append({
            "id": change.id,
            "fieldId": change.key[len(PREFIX):],
            "previousValue": change.previous_value,
            "newValue": change.new_value,
            "reason": change.reason,
            "actorId": str(who.id) if who else None,
            "actorName": name,
            "timestamp": change.changed_at.isoformat(),
        })
    return out
