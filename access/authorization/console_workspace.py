from __future__ import annotations

import logging
from uuid import UUID

from access.authorization.tenant_access import TenantOwnerChecker
from access.selectors import permission_selector
from core.exceptions import (
    BranchNotFoundException,
    PermissionDeniedException,
)
from tenants.models import Branch

logger = logging.getLogger(__name__)

CONSOLE_WORKSPACE_PERMISSIONS = ("orders.view", "reservations.view")
ORDERS_CONSOLE_PERMISSIONS = ("orders.view",)
RESERVATIONS_CONSOLE_PERMISSIONS = ("reservations.view",)


def get_console_branch(*, tenant_id: UUID, branch_id: UUID) -> Branch:
    branch = (
        Branch.objects.select_related("tenant", "tenant__owner", "tenant__owner__user")
        .filter(id=branch_id, tenant_id=tenant_id)
        .first()
    )
    if branch is None:
        raise BranchNotFoundException()
    return branch


def user_is_tenant_owner(*, user, tenant_id: UUID) -> bool:
    return TenantOwnerChecker().is_owner(user=user, tenant_id=tenant_id)


def user_has_console_permissions(
    *,
    user,
    tenant_id: UUID,
    branch_id: UUID,
    permission_slugs: tuple[str, ...],
) -> bool:
    if user_is_tenant_owner(user=user, tenant_id=tenant_id):
        return True
    return permission_selector.user_has_permissions(
        user_id=user.id,
        tenant_id=tenant_id,
        branch_id=branch_id,
        permission_slugs=permission_slugs,
        require_all=False,
    )


def authorize_console_branch(
    *,
    user,
    tenant_id: UUID,
    branch_id: UUID,
    permission_slugs: tuple[str, ...],
) -> Branch:
    """
    Authenticated user must be the tenant owner or hold one of the given
    RBAC permissions at this exact tenant + branch.
    """
    branch = get_console_branch(tenant_id=tenant_id, branch_id=branch_id)
    if user_has_console_permissions(
        user=user,
        tenant_id=tenant_id,
        branch_id=branch_id,
        permission_slugs=permission_slugs,
    ):
        return branch

    logger.info(
        "Console branch access denied user_id=%s tenant_id=%s branch_id=%s",
        getattr(user, "id", None),
        tenant_id,
        branch_id,
    )
    raise PermissionDeniedException()
