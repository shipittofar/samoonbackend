from __future__ import annotations

from access.authorization import TenantOwnerChecker
from access.selectors import permission_selector
from core.exceptions.uploads import (
    UploadPermissionDeniedException,
    UploadValidationException,
)
from tenants.models import Branch, Tenant
from uploads.purposes import PurposePolicy


def _deny(message: str = "You do not have permission to perform this upload action."):
    raise UploadPermissionDeniedException(message)


def user_can_settings_edit(user, tenant_id) -> bool:
    if TenantOwnerChecker().is_owner(user=user, tenant_id=tenant_id):
        return True
    return permission_selector.user_has_permissions(
        user_id=user.id,
        tenant_id=tenant_id,
        branch_id=None,
        permission_slugs=("settings.edit",),
    )


def user_can_menu_manage(user, branch: Branch) -> bool:
    if TenantOwnerChecker().is_owner(user=user, tenant_id=branch.tenant_id):
        return True
    if branch.manager_id == user.id:
        return True
    return permission_selector.user_has_permissions(
        user_id=user.id,
        tenant_id=branch.tenant_id,
        branch_id=branch.id,
        permission_slugs=("menu.manage",),
    )


def resolve_branch_id(*, branch_id=None, entity_type: str = "", entity_id: str = ""):
    """Map upload entity metadata to a Branch id. Never treat a menu row UUID as a branch."""
    if branch_id:
        return branch_id
    if not entity_id:
        return None
    if entity_type == "branch":
        return entity_id
    if entity_type == "menu_item":
        from menu.models import MenuItem

        row = MenuItem.objects.filter(pk=entity_id).only("branch_id").first()
        return getattr(row, "branch_id", None)
    if entity_type == "menu_category":
        from menu.models import MenuCategory

        row = MenuCategory.objects.filter(pk=entity_id).only("branch_id").first()
        return getattr(row, "branch_id", None)
    if entity_type == "menu_tag":
        from menu.models import Tag

        row = Tag.objects.filter(pk=entity_id).only("branch_id").first()
        return getattr(row, "branch_id", None)
    return None


def assert_purpose_authorized(
    *,
    user,
    policy: PurposePolicy,
    tenant_id=None,
    branch_id=None,
    entity_type: str = "",
    entity_id: str = "",
) -> Tenant | Branch | None:
    if policy.authz == "self":
        if tenant_id:
            raise UploadValidationException("user_avatar must not include a tenant.")
        return None

    if not tenant_id:
        raise UploadValidationException("tenant_id is required for this upload purpose.")

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        from core.exceptions import TenantNotFoundException

        raise TenantNotFoundException()

    if policy.authz == "tenant_settings":
        if not user_can_settings_edit(user, tenant.id):
            _deny()
        return tenant

    resolved_branch_id = resolve_branch_id(
        branch_id=branch_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    branch = None
    if resolved_branch_id:
        branch = Branch.objects.filter(id=resolved_branch_id).select_related("tenant").first()
        if branch is None or str(branch.tenant_id) != str(tenant.id):
            from core.exceptions import BranchNotFoundException

            raise BranchNotFoundException()

    if policy.authz == "branch_settings":
        if branch is None:
            raise UploadValidationException("entity_id (branch) is required for this purpose.")
        if user_can_settings_edit(user, tenant.id):
            return branch
        if branch.manager_id == user.id:
            return branch
        _deny()

    if policy.authz == "menu":
        if branch is None:
            raise UploadValidationException("branch_id is required for menu uploads.")
        if not user_can_menu_manage(user, branch):
            _deny()
        return branch

    _deny()
    return None
