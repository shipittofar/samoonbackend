from __future__ import annotations

from tenants.models import Tenant, TenantStatus

# Single source of truth for RBAC tenant ineligibility.
# Contract "archived" and other statuses are mapped here only — do not
# expand TenantStatus or scatter status checks across RBAC code.
INELIGIBLE_TENANT_STATUSES = frozenset(
    {
        TenantStatus.CLOSED,
        TenantStatus.INACTIVE,
    }
)


def is_tenant_rbac_eligible(tenant: Tenant) -> bool:
    if not tenant.is_active:
        return False
    return tenant.status not in INELIGIBLE_TENANT_STATUSES
