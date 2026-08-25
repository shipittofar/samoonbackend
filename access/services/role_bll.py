from __future__ import annotations

from django.db import transaction

from access.authorization.admin_role_protection import (
    assert_role_slug_assignable,
    is_protected_admin_role,
    viewer_may_see_admin_role,
)
from access.models import Permission, Role, RolePermission
from access.selectors import permission_selector
from access.services.permission_audit_bll import permission_audit_bll
from access.services.rbac_bll import rbac_bll
from core.exceptions import (
    AdminRoleAccessDeniedException,
    RoleNotFoundException,
    RoleSlugAlreadyExistsException,
    SystemRoleDeleteNotAllowedException,
    SystemRoleModifyNotAllowedException,
    UnknownPermissionIdsException,
    UnknownPermissionSlugsException,
)


class RoleBusinessLogicLayer:
    selectors = permission_selector

    @staticmethod
    def assert_can_modify_role(*, role: Role, actor, can_manage_roles: bool) -> None:
        if is_protected_admin_role(role=role) and not viewer_may_see_admin_role(actor):
            raise AdminRoleAccessDeniedException()
        if role.system_role and not can_manage_roles:
            raise SystemRoleModifyNotAllowedException()

    @staticmethod
    def _resolve_actor(actor_id):
        if actor_id is None:
            return None
        from accounts.models import User

        return User.objects.filter(id=actor_id).first()

    def create_role(
        self,
        *,
        slug: str,
        name: str,
        description: str = "",
        system_role: bool = False,
        actor_id=None,
        actor=None,
        can_manage_roles: bool = False,
    ) -> Role:
        if actor is None and actor_id is not None:
            from accounts.models import User

            actor = User.objects.filter(id=actor_id).first()
        if actor is not None:
            assert_role_slug_assignable(slug=slug, actor=actor)
        if system_role and not can_manage_roles:
            raise SystemRoleModifyNotAllowedException(
                detail="Cannot create system roles through the application API."
            )

        try:
            with transaction.atomic():
                role = Role.objects.create(
                    slug=slug,
                    name=name,
                    description=description,
                    system_role=False,
                )
                permission_audit_bll.record_role_created(role=role, actor_id=actor_id)
        except Exception as exc:
            from django.db import IntegrityError

            if isinstance(exc, IntegrityError):
                raise RoleSlugAlreadyExistsException(
                    detail=f"Role with slug '{slug}' already exists."
                ) from exc
            raise

        rbac_bll.invalidate_reference_caches()
        return role

    def add_permissions(
        self,
        *,
        role_id,
        permission_slugs: list[str],
        actor_id=None,
        can_manage_roles: bool = False,
    ) -> Role:
        role = self._get_role_or_raise(role_id=role_id)
        actor = self._resolve_actor(actor_id)
        self.assert_can_modify_role(
            role=role, actor=actor, can_manage_roles=can_manage_roles
        )
        permissions = list(self.selectors.get_permissions_by_slugs(slugs=permission_slugs))

        self._validate_all_slugs_found(requested=permission_slugs, found=permissions)
        previous_ids = list(
            RolePermission.objects.filter(role_id=role.id).values_list(
                "permission_id", flat=True
            )
        )

        with transaction.atomic():
            for permission in permissions:
                RolePermission.objects.get_or_create(role_id=role.id, permission_id=permission.id)
            permission_audit_bll.record_role_permissions_changed(
                role=role,
                actor_id=actor_id,
                permission_ids=list(
                    RolePermission.objects.filter(role_id=role.id).values_list(
                        "permission_id", flat=True
                    )
                ),
                previous_permission_ids=previous_ids,
            )

        rbac_bll.invalidate_reference_caches()
        rbac_bll.invalidate_effective_permissions_for_role(role)
        return role

    def get_role_permissions(self, *, role_id) -> list[Permission]:
        role = self._get_role_or_raise(role_id=role_id)
        return list(
            Permission.objects.filter(role_permissions__role_id=role.id).order_by(
                "resource", "action"
            )
        )

    def replace_role_permissions(
        self,
        *,
        role_id,
        permission_ids: list,
        actor_id=None,
        can_manage_roles: bool = False,
    ) -> Role:
        role = self._get_role_or_raise(role_id=role_id)
        actor = self._resolve_actor(actor_id)
        self.assert_can_modify_role(
            role=role, actor=actor, can_manage_roles=can_manage_roles
        )
        unique_ids = list(dict.fromkeys(permission_ids))
        permissions = list(Permission.objects.filter(id__in=unique_ids))
        if len(permissions) != len(unique_ids):
            found_ids = {str(permission.id) for permission in permissions}
            missing = [str(pid) for pid in unique_ids if str(pid) not in found_ids]
            raise UnknownPermissionIdsException(
                detail=f"Unknown permission id(s): {', '.join(missing)}."
            )

        previous_ids = list(
            RolePermission.objects.filter(role_id=role.id).values_list(
                "permission_id", flat=True
            )
        )

        with transaction.atomic():
            RolePermission.objects.filter(role_id=role.id).delete()
            RolePermission.objects.bulk_create(
                [
                    RolePermission(role_id=role.id, permission_id=permission.id)
                    for permission in permissions
                ]
            )
            permission_audit_bll.record_role_permissions_changed(
                role=role,
                actor_id=actor_id,
                permission_ids=unique_ids,
                previous_permission_ids=previous_ids,
            )

        rbac_bll.invalidate_reference_caches()
        rbac_bll.invalidate_effective_permissions_for_role(role)
        return role

    def delete_role(
        self,
        *,
        role_id,
        actor_id=None,
        can_manage_roles: bool = False,
    ) -> None:
        role = self._get_role_or_raise(role_id=role_id)
        actor = self._resolve_actor(actor_id)
        self.assert_can_modify_role(
            role=role, actor=actor, can_manage_roles=can_manage_roles
        )

        if role.system_role:
            raise SystemRoleDeleteNotAllowedException()

        with transaction.atomic():
            permission_audit_bll.record_role_deleted(role=role, actor_id=actor_id)
            role.delete()

        rbac_bll.invalidate_reference_caches()
        rbac_bll.invalidate_effective_permissions_for_role(role)

    def _get_role_or_raise(self, *, role_id) -> Role:
        try:
            return Role.objects.get(id=role_id)
        except Role.DoesNotExist as exc:
            raise RoleNotFoundException() from exc

    def _validate_all_slugs_found(self, *, requested: list[str], found: list) -> None:
        found_slugs = {permission.slug for permission in found}
        missing_slugs = set(requested) - found_slugs
        if missing_slugs:
            raise UnknownPermissionSlugsException(
                detail=f"Unknown permission slug(s): {', '.join(sorted(missing_slugs))}."
            )


role_service = RoleBusinessLogicLayer()
