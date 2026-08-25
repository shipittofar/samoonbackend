from __future__ import annotations

from django.db.models import Q, QuerySet

from access.constants import SystemRoleSlug
from access.models import PermissionAudit, Role, StaffAssignment
from core.exceptions import AdminRoleAccessDeniedException, RoleNotFoundException

PROTECTED_ADMIN_SLUG = SystemRoleSlug.ADMIN


def viewer_may_see_admin_role(user) -> bool:
    """Only Django superusers may see or assign the protected admin RBAC role."""
    return bool(user and getattr(user, "is_authenticated", False) and user.is_superuser)


def is_protected_admin_role(
    *,
    role: Role | None = None,
    role_slug: str | None = None,
    role_id=None,
) -> bool:
    if role is not None:
        return role.slug == PROTECTED_ADMIN_SLUG
    if role_slug is not None:
        return role_slug == PROTECTED_ADMIN_SLUG
    if role_id is not None:
        return Role.objects.filter(id=role_id, slug=PROTECTED_ADMIN_SLUG).exists()
    return False


def filter_roles_queryset_for_viewer(queryset: QuerySet[Role], user) -> QuerySet[Role]:
    if viewer_may_see_admin_role(user):
        return queryset
    return queryset.exclude(slug=PROTECTED_ADMIN_SLUG)


def filter_assignments_queryset_for_viewer(
    queryset: QuerySet[StaffAssignment],
    user,
) -> QuerySet[StaffAssignment]:
    if viewer_may_see_admin_role(user):
        return queryset
    return queryset.exclude(role__slug=PROTECTED_ADMIN_SLUG)


def filter_permission_audit_queryset_for_viewer(
    queryset: QuerySet[PermissionAudit],
    user,
) -> QuerySet[PermissionAudit]:
    if viewer_may_see_admin_role(user):
        return queryset
    return queryset.exclude(
        Q(metadata__has_key="role_slug")
        & Q(metadata__role_slug=PROTECTED_ADMIN_SLUG)
    )


def filter_role_slugs(slugs, user) -> list[str]:
    if viewer_may_see_admin_role(user):
        return list(slugs)
    return [slug for slug in slugs if slug != PROTECTED_ADMIN_SLUG]


def filter_role_dicts_for_viewer(roles: list[dict], user) -> list[dict]:
    if viewer_may_see_admin_role(user):
        return roles
    return [role for role in roles if role.get("slug") != PROTECTED_ADMIN_SLUG]


def assert_role_visible_to_viewer(*, role: Role, viewer) -> None:
    if is_protected_admin_role(role=role) and not viewer_may_see_admin_role(viewer):
        raise RoleNotFoundException()


def assert_role_assignable_by_actor(*, role: Role, actor) -> None:
    if is_protected_admin_role(role=role) and not viewer_may_see_admin_role(actor):
        raise AdminRoleAccessDeniedException()


def assert_role_slug_assignable(*, slug: str, actor) -> None:
    if slug == PROTECTED_ADMIN_SLUG and not viewer_may_see_admin_role(actor):
        raise AdminRoleAccessDeniedException()
