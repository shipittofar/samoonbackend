"""Shared Tenant visibility/usability fields for API responses.

``is_active`` — whether the tenant should be displayed (visibility).
``status`` — whether the tenant is usable/operational (active/inactive/closed).
"""
from __future__ import annotations

from rest_framework import serializers


class TenantSummarySerializer(serializers.Serializer):
    """Minimal tenant identity + visibility/usability state."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)


def build_tenant_summary(obj) -> dict | None:
    """Build a tenant summary dict from a Tenant model, DTO, or denormalized branch row."""
    if obj is None:
        return None

    tenant_id = getattr(obj, "id", None) or getattr(obj, "tenant_id", None)
    if tenant_id is None:
        return None

    name = getattr(obj, "name", None) or getattr(obj, "tenant_name", None) or ""
    slug = getattr(obj, "slug", None) or getattr(obj, "tenant_slug", None) or ""

    if hasattr(obj, "tenant_is_active"):
        is_active = obj.tenant_is_active
    else:
        is_active = getattr(obj, "is_active", None)
    if is_active is None:
        is_active = False

    if hasattr(obj, "tenant_status"):
        status = obj.tenant_status
    else:
        status = getattr(obj, "status", None)
    if status is None:
        status = "inactive"

    return {
        "id": tenant_id,
        "name": name,
        "slug": slug,
        "is_active": is_active,
        "status": status,
    }
