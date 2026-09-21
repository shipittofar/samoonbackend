from __future__ import annotations

from access.authorization import TenantOwnerChecker
from access.selectors import permission_selector
from core.exceptions.uploads import (
    UploadPermissionDeniedException,
    UploadValidationException,
)
from tenants.models import Branch, Tenant
from uploads.purposes import PurposePolicy

# Canonical platform homepage media context for purpose=website_media.
# Tenant-scoped website_media still requires tenant_id + settings.edit.
PLATFORM_HOMEPAGE_ENTITY_TYPE = "platform"
PLATFORM_HOMEPAGE_ENTITY_ID = "homepage"


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


def user_can_platform_cms(user) -> bool:
    """Platform CMS operators (homepage hero, etc.). Staff or superuser only."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )


def is_platform_homepage_media(
    *,
    purpose: str = "",
    entity_type: str = "",
    entity_id: str = "",
    tenant_id=None,
) -> bool:
    """
    True only for the explicit platform homepage website_media contract:
    purpose website_media (when provided), entity_type=platform, entity_id=homepage,
    and no tenant_id.
    """
    if purpose and purpose != "website_media":
        return False
    if tenant_id not in (None, ""):
        return False
    return (
        str(entity_type or "") == PLATFORM_HOMEPAGE_ENTITY_TYPE
        and str(entity_id or "") == PLATFORM_HOMEPAGE_ENTITY_ID
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

    # Platform homepage hero: website_media without tenant_id, only for
    # entity_type=platform + entity_id=homepage, authorized as platform CMS.
    if policy.purpose == "website_media" and is_platform_homepage_media(
        purpose=policy.purpose,
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant_id,
    ):
        if not user_can_platform_cms(user):
            _deny("Platform homepage media requires platform CMS privileges.")
        return None

    if policy.purpose == "website_media" and (
        str(entity_type or "") == PLATFORM_HOMEPAGE_ENTITY_TYPE
        or str(entity_id or "") == PLATFORM_HOMEPAGE_ENTITY_ID
    ):
        # Reject ambiguous mixes (platform markers with tenant_id, or incomplete markers).
        raise UploadValidationException(
            "Platform homepage website_media requires entity_type=platform, "
            "entity_id=homepage, and no tenant_id."
        )

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
