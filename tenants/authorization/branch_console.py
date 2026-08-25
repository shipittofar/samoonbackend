from __future__ import annotations

from rest_framework.permissions import BasePermission

from access.authorization import TenantOwnerChecker
from access.selectors import permission_selector
from core.exceptions import BranchNotFoundException, PermissionDeniedException
from tenants.selectors.branch_metrics_dal import BranchMetricsDataAccessLayer


class RequireBranchAnalyticsPermission(BasePermission):
    """Console permission for branch-scoped endpoints without tenant_id in the URL."""

    required_permission = "analytics.view"
    branch_lookup_kwarg = "branch_id"

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        branch_id = view.kwargs.get(self.branch_lookup_kwarg)
        branch = BranchMetricsDataAccessLayer.get_branch_for_metrics(
            branch_id=branch_id
        )
        if branch is None:
            raise BranchNotFoundException()

        view._metrics_branch = branch

        if TenantOwnerChecker().is_owner(
            user=request.user, tenant_id=branch.tenant_id
        ):
            return True

        has_perm = permission_selector.user_has_permissions(
            user_id=request.user.id,
            tenant_id=branch.tenant_id,
            branch_id=branch.id,
            permission_slugs=(self.required_permission,),
        )
        if not has_perm:
            raise PermissionDeniedException(
                f"You do not have the required permission(s): '{self.required_permission}'."
            )

        return True
