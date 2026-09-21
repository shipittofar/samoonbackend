from __future__ import annotations

from rest_framework.permissions import BasePermission

from access.authorization import TenantOwnerChecker
from access.selectors import permission_selector
from core.exceptions import BranchNotFoundException, PermissionDeniedException
from tenants.models import Branch


class RequireBranchMenuManagePermission(BasePermission):
    """
    Allow tenant owners, branch managers, or users with menu.manage
    permission to manage branch-scoped menu resources (tags, etc.).
    """

    required_permission = "menu.manage"
    branch_lookup_kwarg = "branch_id"

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        branch_id = view.kwargs.get(self.branch_lookup_kwarg)
        if branch_id is None:
            branch_id = request.query_params.get("branch_id")
        if branch_id is None and hasattr(request, "data"):
            branch_id = request.data.get("branch_id")
            if branch_id is None:
                items = request.data.get("items") or request.data.get("categories") or []
                if isinstance(items, list) and items:
                    first = items[0]
                    if hasattr(first, "get"):
                        branch_id = first.get("branch_id")
        if branch_id is None:
            return False

        branch = Branch.objects.filter(id=branch_id).select_related("tenant").first()
        if branch is None:
            raise BranchNotFoundException()

        view._menu_branch = branch

        if TenantOwnerChecker().is_owner(
            user=request.user,
            tenant_id=branch.tenant_id,
        ):
            return True

        if branch.manager_id == request.user.id:
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


def assert_branch_menu_write(user, branch_id) -> Branch:
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedException(
            "You do not have the required permission(s): 'menu.manage'."
        )
    branch = Branch.objects.filter(id=branch_id).select_related("tenant").first()
    if branch is None:
        raise BranchNotFoundException()
    if TenantOwnerChecker().is_owner(user=user, tenant_id=branch.tenant_id):
        return branch
    if branch.manager_id == user.id:
        return branch
    has_perm = permission_selector.user_has_permissions(
        user_id=user.id,
        tenant_id=branch.tenant_id,
        branch_id=branch.id,
        permission_slugs=("menu.manage",),
    )
    if not has_perm:
        raise PermissionDeniedException(
            "You do not have the required permission(s): 'menu.manage'."
        )
    return branch
