from __future__ import annotations

from tenants.models import Tenant, TenantStatus
from tenants.models.tenant import OwnerStatus

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
    if tenant.status in INELIGIBLE_TENANT_STATUSES:
        return False
    # A suspended owner's businesses are suspended with them (owner and staff
    # alike; platform superusers still get in). Empty / pending status = active.
    return tenant.owner.status != OwnerStatus.SUSPENDED


def is_owner_suspended(user_id) -> bool:
    """Owner.status = suspended: no owner access and no new businesses."""
    from tenants.models import Owner

    return Owner.objects.filter(user_id=user_id, status=OwnerStatus.SUSPENDED).exists()
