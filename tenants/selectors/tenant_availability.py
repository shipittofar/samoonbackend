"""Shared tenant visibility and operational availability helpers."""
from __future__ import annotations

from tenants.models import TenantStatus

# Branch ORM lookups ------------------------------------------------------------

# Visibility-only: tenant should be displayed.
VISIBILITY_TENANT_LOOKUP = {
    "tenant__is_active": True,
}

# Operational: tenant can accept orders / delivery / checkout.
OPERATIONAL_TENANT_LOOKUP = {
    "tenant__is_active": True,
    "tenant__status": TenantStatus.ACTIVE,
}

# Public directory/catalog surfaces (discover, /api/tenants/, global branches)
# intentionally list only tenants that are both visible and operationally active.
PUBLIC_TENANT_LOOKUP = OPERATIONAL_TENANT_LOOKUP

# Tenant ORM filter (no ``tenant__`` prefix) for public catalog querysets.
PUBLIC_TENANT_FILTER = {
    "is_active": True,
    "status": TenantStatus.ACTIVE,
}


def tenant_is_publicly_visible(tenant) -> bool:
    """Return whether the tenant should be displayed (visibility)."""
    return bool(getattr(tenant, "is_active", False))


def tenant_is_operationally_available(tenant) -> bool:
    """Return whether the tenant can perform business operations."""
    return bool(
        tenant_is_publicly_visible(tenant)
        and getattr(tenant, "status", None) == TenantStatus.ACTIVE
    )


def tenant_is_publicly_listable(tenant) -> bool:
    """Return whether the tenant may appear on public catalog surfaces.

    Catalog endpoints align with ``PUBLIC_TENANT_FILTER`` / ``PUBLIC_TENANT_LOOKUP``:
    visible **and** operationally active.
    """
    return tenant_is_operationally_available(tenant)
