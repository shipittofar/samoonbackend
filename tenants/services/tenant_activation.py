"""Tenant activation lifecycle driven by active branch count."""

from tenants.models import Branch, BranchStatus, Tenant, TenantStatus
from tenants.selectors import TenantDataAccessLayer

tenant_dal = TenantDataAccessLayer()


def lifecycle_branches_exist(tenant_id) -> bool:
    """Return whether the tenant has at least one non-deleted branch."""
    return Branch.objects.filter(
        tenant_id=tenant_id,
        status=BranchStatus.ACTIVE,
        is_active=True,
    ).exists()


def enforce_tenant_activation_status(tenant: Tenant) -> Tenant:
    """Align ``tenant.status`` with branch lifecycle rules.

    Active when at least one lifecycle branch exists; otherwise inactive.
    ``CLOSED`` tenants are left unchanged.
    """
    if tenant.status == TenantStatus.CLOSED:
        return tenant

    if lifecycle_branches_exist(tenant.id):
        if tenant.status != TenantStatus.ACTIVE:
            return tenant_dal.activate_tenant(tenant)
        return tenant

    if tenant.status != TenantStatus.INACTIVE:
        return tenant_dal.inactive_tenant(tenant)
    return tenant


def initial_tenant_status() -> str:
    """Status for a newly created tenant with zero branches."""
    return TenantStatus.INACTIVE
