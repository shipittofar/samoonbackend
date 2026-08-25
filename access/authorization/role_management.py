from __future__ import annotations

from rest_framework.permissions import BasePermission

from access.selectors import permission_selector
from core.exceptions import PermissionDeniedException


def user_can_manage_role_definitions(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return permission_selector.user_has_manage_roles_permission(user_id=user.id)


class CanManageRoleDefinitions(BasePermission):
    """Platform role-definition management — superuser, staff, or rbac.manage_roles."""

    message = "Requires platform role management privileges."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if user_can_manage_role_definitions(request.user):
            return True
        raise PermissionDeniedException(
            detail="Requires platform role management privileges (rbac.manage_roles)."
        )
