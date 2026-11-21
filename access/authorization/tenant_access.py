from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from access.authorization.platform import is_platform_superuser
from access.constants.tenant_eligibility import is_tenant_rbac_eligible
from access.selectors import permission_selector
from core.exceptions import PermissionDeniedException, TenantAccessDeniedException
from tenants.models import Tenant


class TenantOwnerChecker:
    """
    Owners are business entities (places.Owner), never StaffMembership rows
    (see StaffMembership.clean()), so ownership can't be checked through
    role permissions. It must be checked against the Owner <-> Tenant
    relation directly.

    NOTE: adjust `_get_tenant_queryset` to match the actual Owner <-> Tenant
    relation in this codebase.
    """

    def is_owner(self, *, user, tenant_id) -> bool:
        """Owner-level access: the tenant's owner, or a platform superuser
        (who has owner-level access to every tenant)."""
        if is_platform_superuser(user):
            return True
        from tenants.models import Tenant

        return Tenant.objects.filter(id=tenant_id, owner__user_id=user.id).exists()


class BaseTenantPermission(BasePermission):
    required_permissions: tuple[str, ...] = ()
    require_all: bool = True
    tenant_lookup_kwarg: str = "tenant_id"
    branch_lookup_kwarg: str = "branch_id"

    owner_checker_class = TenantOwnerChecker
    selector = permission_selector

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        tenant_id = self._get_tenant_id(view)
        if is_platform_superuser(request.user):
            # Every permission in every tenant, whatever its status.
            return True
        branch_id = self._get_branch_id(view)

        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None or not is_tenant_rbac_eligible(tenant):
            raise TenantAccessDeniedException(
                detail="Tenant is not eligible for RBAC access."
            )

        if self.owner_checker_class().is_owner(user=request.user, tenant_id=tenant_id):
            return True

        if not self.required_permissions:
            return True

        has_perm = self.selector.user_has_permissions(
            user_id=request.user.id,
            tenant_id=tenant_id,
            branch_id=branch_id,
            permission_slugs=self.required_permissions,
            require_all=self.require_all,
        )

        if not has_perm:
            raise PermissionDeniedException(detail=self._build_denied_message())

        return True

    def _build_denied_message(self) -> str:
        joiner = "' and '" if self.require_all else "' or '"
        slugs = joiner.join(self.required_permissions)
        return f"You do not have the required permission(s): '{slugs}'."

    def _get_tenant_id(self, view):
        tenant_id = view.kwargs.get(self.tenant_lookup_kwarg)
        if tenant_id is None:
            raise NotFound(f"'{self.tenant_lookup_kwarg}' was not found in the URL.")
        return tenant_id

    def _get_branch_id(self, view):
        return view.kwargs.get(self.branch_lookup_kwarg)


class RequirePermission:
    """
    Factory that builds a `BaseTenantPermission` subclass, so it can be
    dropped into `permission_classes` like any other DRF permission class.

    Usage:
        permission_classes = (IsAuthenticated, RequirePermission("tenant.delete"))
        permission_classes = (IsAuthenticated, RequirePermission("menu.manage", "menu.view", require_all=False))
        permission_classes = (IsAuthenticated, RequirePermission("branch.manage", branch_lookup_kwarg="id"))
    """

    def __new__(
        cls,
        *slugs: str,
        require_all: bool = True,
        tenant_lookup_kwarg: str = "tenant_id",
        branch_lookup_kwarg: str = "branch_id",
    ) -> type[BaseTenantPermission]:
        return type(
            f"RequirePermission_{'_'.join(slugs) or 'any'}",
            (BaseTenantPermission,),
            {
                "required_permissions": slugs,
                "require_all": require_all,
                "tenant_lookup_kwarg": tenant_lookup_kwarg,
                "branch_lookup_kwarg": branch_lookup_kwarg,
            },
        )