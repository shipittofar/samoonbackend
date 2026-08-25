from __future__ import annotations

from access.models import PermissionAudit, PermissionAuditAction


class PermissionAuditBusinessLogicLayer:
    @staticmethod
    def _audit_metadata(**kwargs) -> dict:
        return {key: value for key, value in kwargs.items() if value is not None}

    @staticmethod
    def record(
        *,
        action: str,
        tenant_id,
        actor_id=None,
        membership_id=None,
        assignment_id=None,
        permission_id=None,
        metadata: dict | None = None,
    ) -> PermissionAudit:
        return PermissionAudit.objects.create(
            action=action,
            tenant_id=tenant_id,
            actor_id=actor_id,
            membership_id=membership_id,
            assignment_id=assignment_id,
            permission_id=permission_id,
            metadata=metadata or {},
        )

    def record_role_created(self, *, role, actor_id) -> PermissionAudit:
        return self.record(
            action=PermissionAuditAction.ROLE_CREATED,
            tenant_id=None,
            actor_id=actor_id,
            metadata=self._audit_metadata(
                role_id=str(role.id),
                role_slug=role.slug,
                new_value={
                    "name": role.name,
                    "slug": role.slug,
                    "system_role": role.system_role,
                },
            ),
        )

    def record_role_deleted(self, *, role, actor_id) -> PermissionAudit:
        return self.record(
            action=PermissionAuditAction.ROLE_DELETED,
            tenant_id=None,
            actor_id=actor_id,
            metadata=self._audit_metadata(
                role_id=str(role.id),
                role_slug=role.slug,
                old_value={
                    "name": role.name,
                    "slug": role.slug,
                    "system_role": role.system_role,
                },
            ),
        )

    def record_assignment_created(self, *, assignment, actor_id) -> PermissionAudit:
        membership = assignment.membership
        return self.record(
            action=PermissionAuditAction.ASSIGNMENT_CREATED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=assignment.membership_id,
            assignment_id=assignment.id,
            metadata=self._audit_metadata(
                target_user=str(membership.user_id),
                role_id=str(assignment.role_id),
                role_slug=assignment.role.slug,
                status=assignment.status,
                new_value={
                    "role_slug": assignment.role.slug,
                    "status": assignment.status,
                },
            ),
        )

    def record_assignment_updated(self, *, assignment, actor_id, metadata=None) -> PermissionAudit:
        membership = assignment.membership
        base = {
            "target_user": str(membership.user_id),
            "role_id": str(assignment.role_id),
            "role_slug": assignment.role.slug,
            "status": assignment.status,
        }
        if metadata:
            base.update(metadata)
        return self.record(
            action=PermissionAuditAction.ASSIGNMENT_UPDATED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=assignment.membership_id,
            assignment_id=assignment.id,
            metadata=base,
        )

    def record_assignment_revoked(self, *, assignment, actor_id) -> PermissionAudit:
        membership = assignment.membership
        return self.record(
            action=PermissionAuditAction.ASSIGNMENT_REVOKED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=assignment.membership_id,
            assignment_id=assignment.id,
            metadata=self._audit_metadata(
                target_user=str(membership.user_id),
                role_id=str(assignment.role_id),
                role_slug=assignment.role.slug,
                old_value={"status": "active"},
                new_value={"status": assignment.status},
            ),
        )

    def record_override_created(self, *, override, actor_id) -> PermissionAudit:
        membership = override.membership
        return self.record(
            action=PermissionAuditAction.OVERRIDE_CREATED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=override.membership_id,
            permission_id=override.permission_id,
            metadata=self._audit_metadata(
                target_user=str(membership.user_id),
                permission_slug=override.permission.slug,
                new_value={"effect": override.effect},
            ),
        )

    def record_override_updated(self, *, override, actor_id, previous_effect) -> PermissionAudit:
        membership = override.membership
        return self.record(
            action=PermissionAuditAction.OVERRIDE_UPDATED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=override.membership_id,
            permission_id=override.permission_id,
            metadata=self._audit_metadata(
                target_user=str(membership.user_id),
                permission_slug=override.permission.slug,
                old_value={"effect": previous_effect},
                new_value={"effect": override.effect},
            ),
        )

    def record_override_removed(self, *, override, actor_id) -> PermissionAudit:
        membership = override.membership
        return self.record(
            action=PermissionAuditAction.OVERRIDE_REMOVED,
            tenant_id=membership.tenant_id,
            actor_id=actor_id,
            membership_id=override.membership_id,
            permission_id=override.permission_id,
            metadata=self._audit_metadata(
                target_user=str(membership.user_id),
                permission_slug=override.permission.slug,
                old_value={"effect": override.effect},
            ),
        )

    def record_role_permissions_changed(
        self,
        *,
        role,
        actor_id,
        permission_ids: list,
        previous_permission_ids: list | None = None,
        tenant_id=None,
    ) -> PermissionAudit:
        return self.record(
            action=PermissionAuditAction.ROLE_PERMISSIONS_CHANGED,
            tenant_id=tenant_id,
            actor_id=actor_id,
            metadata=self._audit_metadata(
                role_id=str(role.id),
                role_slug=role.slug,
                old_value=(
                    {"permission_ids": [str(pid) for pid in previous_permission_ids]}
                    if previous_permission_ids is not None
                    else None
                ),
                new_value={"permission_ids": [str(pid) for pid in permission_ids]},
            ),
        )

    def record_ownership_transfer(
        self,
        *,
        tenant_id,
        actor_id,
        old_owner_id,
        new_owner_id,
    ) -> PermissionAudit:
        return self.record(
            action=PermissionAuditAction.OWNERSHIP_TRANSFERRED,
            tenant_id=tenant_id,
            actor_id=actor_id,
            metadata=self._audit_metadata(
                old_owner=str(old_owner_id),
                new_owner=str(new_owner_id),
                old_value={"owner_id": str(old_owner_id)},
                new_value={"owner_id": str(new_owner_id)},
            ),
        )


permission_audit_bll = PermissionAuditBusinessLogicLayer()
