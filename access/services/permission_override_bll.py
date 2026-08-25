from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from access.models import Permission, PermissionOverride, PermissionOverrideEffect, StaffMembership
from access.services.permission_audit_bll import permission_audit_bll
from access.services.rbac_bll import rbac_bll
from core.exceptions import (
    PermissionNotFoundException,
    PermissionOverrideNotFoundException,
    StaffMembershipNotFoundException,
)


class PermissionOverrideBusinessLogicLayer:
    def list_overrides(self, *, tenant_id, membership_id=None):
        queryset = PermissionOverride.objects.filter(
            membership__tenant_id=tenant_id,
        ).select_related("permission", "membership", "created_by")
        if membership_id is not None:
            queryset = queryset.filter(membership_id=membership_id)
        return queryset.order_by("-created_at")

    def create_override(
        self,
        *,
        tenant_id,
        membership_id,
        permission_id,
        effect: str,
        created_by_id,
    ) -> PermissionOverride:
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id
        )
        permission = self._get_permission_or_raise(permission_id=permission_id)
        self._validate_effect(effect)

        try:
            with transaction.atomic():
                override = PermissionOverride.objects.create(
                    membership=membership,
                    permission=permission,
                    effect=effect,
                    created_by_id=created_by_id,
                )
                permission_audit_bll.record_override_created(
                    override=override, actor_id=created_by_id
                )
        except IntegrityError as exc:
            raise ValidationError(
                {"permission_id": "An override for this permission already exists."}
            ) from exc

        rbac_bll.invalidate_effective_permissions_for_membership(membership)
        return self._reload_override(override.id)

    def update_override(
        self,
        *,
        tenant_id,
        override_id,
        effect: str,
        actor_id,
    ) -> PermissionOverride:
        override = self._get_override_in_tenant_or_raise(
            tenant_id=tenant_id, override_id=override_id
        )
        self._validate_effect(effect)
        previous_effect = override.effect
        override.effect = effect

        with transaction.atomic():
            override.save(update_fields=["effect", "updated_at"])
            permission_audit_bll.record_override_updated(
                override=override,
                actor_id=actor_id,
                previous_effect=previous_effect,
            )

        rbac_bll.invalidate_effective_permissions_for_membership(override.membership)
        return self._reload_override(override.id)

    def delete_override(self, *, tenant_id, override_id, actor_id) -> None:
        override = self._get_override_in_tenant_or_raise(
            tenant_id=tenant_id, override_id=override_id
        )
        membership = override.membership

        with transaction.atomic():
            permission_audit_bll.record_override_removed(
                override=override, actor_id=actor_id
            )
            override.delete()

        rbac_bll.invalidate_effective_permissions_for_membership(membership)

    @staticmethod
    def _validate_effect(effect: str) -> None:
        if effect not in PermissionOverrideEffect.values:
            raise ValidationError(
                {"effect": f"Must be one of: {', '.join(PermissionOverrideEffect.values)}."}
            )

    @staticmethod
    def _get_membership_in_tenant_or_raise(*, tenant_id, membership_id) -> StaffMembership:
        try:
            return StaffMembership.objects.get(id=membership_id, tenant_id=tenant_id)
        except StaffMembership.DoesNotExist as exc:
            raise StaffMembershipNotFoundException() from exc

    @staticmethod
    def _get_permission_or_raise(*, permission_id) -> Permission:
        try:
            return Permission.objects.get(id=permission_id)
        except Permission.DoesNotExist as exc:
            raise PermissionNotFoundException() from exc

    @staticmethod
    def _get_override_in_tenant_or_raise(*, tenant_id, override_id) -> PermissionOverride:
        override = (
            PermissionOverride.objects.select_related("membership", "permission")
            .filter(id=override_id, membership__tenant_id=tenant_id)
            .first()
        )
        if override is None:
            raise PermissionOverrideNotFoundException()
        return override

    @staticmethod
    def _reload_override(override_id) -> PermissionOverride:
        return (
            PermissionOverride.objects.select_related(
                "permission", "membership", "created_by"
            )
            .get(id=override_id)
        )


permission_override_bll = PermissionOverrideBusinessLogicLayer()
