from __future__ import annotations

from rest_framework.permissions import BasePermission

from core.exceptions import PermissionDeniedException


class IsSuperuser(BasePermission):
    """Django superusers only. (DRF's IsAdminUser checks ``is_staff``, which only
    means "may open the Django admin" and must not grant API privileges.)"""

    message = "Requires a platform administrator (superuser)."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


def user_can_manage_role_definitions(user) -> bool:
    """Global role definitions are shared by every tenant, so editing them is a
    platform action: Django superusers only. Neither ``is_staff`` (= may open the
    Django admin) nor any tenant-scoped grant may unlock it — a tenant-scoped
    ``rbac.manage_roles`` let one tenant's staff rewrite roles for all tenants."""
    return bool(user and user.is_authenticated and user.is_superuser)


class CanManageRoleDefinitions(BasePermission):
    """Platform role-definition management — Django superusers only."""

    message = "Requires platform role management privileges."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if user_can_manage_role_definitions(request.user):
            return True
        raise PermissionDeniedException(
            detail="Requires platform role management privileges (superuser)."
        )
