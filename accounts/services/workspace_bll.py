from __future__ import annotations

import logging
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from accounts.models import User, UserTenantPreference
from access.services.assignment_scope import (
    filter_assignments_for_authorization,
    membership_covers_branch,
)
from core.exceptions import (
    ActiveBranchTenantMismatchException,
    BranchNotFoundException,
    NotAMemberOfBranchException,
    NotAMemberOfTenantException,
)
from tenants.models import Branch

logger = logging.getLogger(__name__)


def _same_uuid(left, right) -> bool:
    """Compare UUID-ish values without false negatives from str vs UUID."""
    if left is None or right is None:
        return left is None and right is None
    return str(left) == str(right)


def _coerce_uuid(value):
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _workspace_switch_diagnostics(
    *,
    user: User,
    requested_branch_id,
    resolved_branch: Branch | None = None,
    raise_source: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Non-sensitive context for switch-branch mismatch debugging."""
    from access.services.membership_bll import membership_service

    available_user_tenants = sorted(membership_service.get_valid_tenant_ids(user))
    available_user_branches: list[str] = []
    for tenant_id in available_user_tenants:
        available_user_branches.extend(
            str(branch_id)
            for branch_id in Branch.objects.filter(tenant_id=tenant_id).values_list(
                "id", flat=True
            )
        )

    active_tenant_id = user.active_tenant_id
    resolved_branch_tenant_id = (
        resolved_branch.tenant_id if resolved_branch is not None else None
    )
    payload = {
        "user_id": str(user.pk),
        "active_tenant_id": (
            str(active_tenant_id) if active_tenant_id is not None else None
        ),
        "active_tenant_id_type": type(active_tenant_id).__name__,
        "requested_branch_id": (
            str(requested_branch_id) if requested_branch_id is not None else None
        ),
        "resolved_branch_id": (
            str(resolved_branch.id) if resolved_branch is not None else None
        ),
        "resolved_branch_tenant_id": (
            str(resolved_branch_tenant_id)
            if resolved_branch_tenant_id is not None
            else None
        ),
        "resolved_branch_tenant_id_type": (
            type(resolved_branch_tenant_id).__name__
            if resolved_branch is not None
            else None
        ),
        "ids_equal": _same_uuid(active_tenant_id, resolved_branch_tenant_id),
        "available_user_tenants": available_user_tenants,
        "available_user_branches": available_user_branches,
    }
    if raise_source is not None:
        payload["raise_source"] = raise_source
    if extra:
        payload.update(extra)
    return payload


def _raise_active_branch_tenant_mismatch(
    *,
    user: User,
    requested_branch_id,
    resolved_branch: Branch | None = None,
    raise_source: str,
    extra: dict | None = None,
    cause: BaseException | None = None,
) -> None:
    diagnostics = _workspace_switch_diagnostics(
        user=user,
        requested_branch_id=requested_branch_id,
        resolved_branch=resolved_branch,
        raise_source=raise_source,
        extra=extra,
    )
    logger.warning(
        "active_branch_tenant_mismatch raise_source=%s",
        raise_source,
        extra=diagnostics,
    )
    exc = ActiveBranchTenantMismatchException(diagnostics=diagnostics)
    if cause is not None:
        raise exc from cause
    raise exc


def _save_workspace_pointers(locked: User, user: User, update_fields: list[str]) -> None:
    locked.save(update_fields=update_fields)
    user.active_tenant_id = locked.active_tenant_id
    user.active_branch_id = locked.active_branch_id


def _clean_workspace_fields_or_raise(
    locked: User, branch: Branch, raise_source: str
) -> None:
    try:
        locked.clean()
    except DjangoValidationError as exc:
        message_dict = getattr(exc, "message_dict", {}) or {}
        if "active_branch" in message_dict or "active_tenant" in message_dict:
            _raise_active_branch_tenant_mismatch(
                user=locked,
                requested_branch_id=branch.id,
                resolved_branch=branch,
                raise_source=raise_source,
                extra={
                    "validation_messages": message_dict,
                    "clean_active_branch_id": (
                        str(locked.active_branch_id)
                        if locked.active_branch_id is not None
                        else None
                    ),
                    "clean_active_branch_tenant_id": (
                        str(locked.active_branch.tenant_id)
                        if locked.active_branch_id is not None
                        else None
                    ),
                },
                cause=exc,
            )
        logger.exception(
            "Unexpected User.clean ValidationError during workspace update",
            extra={
                **_workspace_switch_diagnostics(
                    user=locked,
                    requested_branch_id=branch.id,
                    resolved_branch=branch,
                ),
                "validation_messages": message_dict,
            },
        )
        raise


class WorkspaceBusinessLogicLayer:
    @staticmethod
    def user_can_access_branch(user: User, branch: Branch) -> bool:
        owner_profile = getattr(user, "owner_profile", None)
        if owner_profile and owner_profile.tenants.filter(id=branch.tenant_id).exists():
            return True

        membership = (
            user.staff_memberships
            .filter(tenant_id=branch.tenant_id, status="active")
            .first()
        )
        if membership is None:
            return False

        assignments = filter_assignments_for_authorization(
            membership.assignments
        ).prefetch_related("locations")
        return membership_covers_branch(assignments, branch.id)

    @staticmethod
    def get_preferred_branch(user: User, tenant_id) -> Branch | None:
        coerced_tenant_id = _coerce_uuid(tenant_id)
        preference = (
            UserTenantPreference.objects.filter(
                user_id=user.pk,
                tenant_id=coerced_tenant_id,
            )
            .select_related("preferred_branch")
            .first()
        )
        if preference is None or preference.preferred_branch_id is None:
            return None
        branch = preference.preferred_branch
        if branch is None or not _same_uuid(branch.tenant_id, coerced_tenant_id):
            return None
        if not WorkspaceBusinessLogicLayer.user_can_access_branch(user, branch):
            return None
        return branch

    @staticmethod
    def persist_preferred_branch(user: User, tenant_id, branch_id) -> None:
        coerced_tenant_id = _coerce_uuid(tenant_id)
        coerced_branch_id = _coerce_uuid(branch_id) if branch_id is not None else None
        preference, _created = UserTenantPreference.objects.get_or_create(
            user_id=user.pk,
            tenant_id=coerced_tenant_id,
            defaults={"preferred_branch_id": coerced_branch_id},
        )
        if preference.preferred_branch_id != coerced_branch_id:
            preference.preferred_branch_id = coerced_branch_id
            preference.save(update_fields=["preferred_branch_id", "updated_at"])

    @staticmethod
    def delete_preferred_branch_for_tenant(user: User, tenant_id) -> None:
        UserTenantPreference.objects.filter(
            user_id=user.pk,
            tenant_id=_coerce_uuid(tenant_id),
        ).delete()

    @staticmethod
    def resolve_workspace_branch(
        user: User,
        tenant_id,
        *,
        locked_user: User | None = None,
        explicit_branch_id=None,
    ) -> Branch | None:
        """
        Resolve the workspace branch for user + tenant.

        Priority: explicit branch → stored preference → active branch (same tenant)
        → authorized fallback (is_default, created_at).
        """
        user_ref = locked_user or user
        coerced_tenant_id = _coerce_uuid(tenant_id)

        if explicit_branch_id is not None:
            branch = (
                Branch.objects.filter(
                    id=_coerce_uuid(explicit_branch_id),
                    tenant_id=coerced_tenant_id,
                )
                .select_related("tenant")
                .first()
            )
            if branch is None:
                return None
            if WorkspaceBusinessLogicLayer.user_can_access_branch(user_ref, branch):
                return branch
            return None

        preferred = WorkspaceBusinessLogicLayer.get_preferred_branch(
            user_ref, coerced_tenant_id
        )
        if preferred is not None:
            return preferred

        if (
            user_ref.active_branch_id
            and _same_uuid(user_ref.active_tenant_id, coerced_tenant_id)
        ):
            active_branch = user_ref.active_branch
            if active_branch and WorkspaceBusinessLogicLayer.user_can_access_branch(
                user_ref, active_branch
            ):
                return active_branch

        return WorkspaceBusinessLogicLayer._resolve_fallback_branch(
            user_ref, coerced_tenant_id
        )

    @staticmethod
    def _resolve_fallback_branch(user: User, tenant_id) -> Branch | None:
        branches = (
            Branch.objects.filter(tenant_id=tenant_id)
            .order_by("-is_default", "created_at")
        )
        for branch in branches:
            if WorkspaceBusinessLogicLayer.user_can_access_branch(user, branch):
                return branch
        return None

    @staticmethod
    @transaction.atomic
    def activate_workspace(
        user: User,
        tenant_id,
        branch_id=None,
        *,
        persist_preference: bool = True,
    ) -> None:
        from access.services.membership_bll import membership_service

        coerced_tenant_id = _coerce_uuid(tenant_id)
        valid_ids = membership_service.get_valid_tenant_ids(user)
        if str(coerced_tenant_id) not in valid_ids:
            raise NotAMemberOfTenantException()

        locked = User.objects.select_for_update().get(pk=user.pk)

        if branch_id is not None:
            branch = (
                Branch.objects.filter(id=_coerce_uuid(branch_id))
                .select_related("tenant")
                .first()
            )
            if branch is None:
                raise BranchNotFoundException()
            if not _same_uuid(branch.tenant_id, coerced_tenant_id):
                _raise_active_branch_tenant_mismatch(
                    user=locked,
                    requested_branch_id=branch.id,
                    resolved_branch=branch,
                    raise_source="activate_workspace_tenant_id_mismatch",
                )
            if not WorkspaceBusinessLogicLayer.user_can_access_branch(locked, branch):
                raise NotAMemberOfBranchException()
            resolved_branch = branch
        else:
            resolved_branch = WorkspaceBusinessLogicLayer.resolve_workspace_branch(
                user,
                coerced_tenant_id,
                locked_user=locked,
            )

        locked.active_tenant_id = coerced_tenant_id
        locked.active_branch = resolved_branch
        if resolved_branch is not None:
            _clean_workspace_fields_or_raise(
                locked, resolved_branch, "activate_workspace_validation"
            )

        _save_workspace_pointers(
            locked, user, ["active_tenant_id", "active_branch_id"]
        )

        if persist_preference and resolved_branch is not None:
            WorkspaceBusinessLogicLayer.persist_preferred_branch(
                locked, coerced_tenant_id, resolved_branch.id
            )

    @staticmethod
    @transaction.atomic
    def ensure_workspace_initialized(user: User) -> None:
        """
        Bootstrap or repair workspace pointers for session endpoints (/auth/me).

        - Single tenant + no active tenant → activate that tenant + resolved branch.
        - Active tenant + no branch → resolve branch for that tenant.
        - Inconsistent pointers → repair when possible.
        """
        from access.services.membership_bll import membership_service

        valid_ids = membership_service.get_valid_tenant_ids(user)
        if not valid_ids:
            return

        locked = User.objects.select_for_update().get(pk=user.pk)

        if locked.active_tenant_id:
            tenant_id = locked.active_tenant_id
            if str(tenant_id) not in valid_ids:
                locked.active_tenant_id = None
                locked.active_branch_id = None
                _save_workspace_pointers(
                    locked, user, ["active_tenant_id", "active_branch_id"]
                )
            elif locked.active_branch_id:
                branch = locked.active_branch
                if (
                    branch is None
                    or not _same_uuid(branch.tenant_id, tenant_id)
                    or not WorkspaceBusinessLogicLayer.user_can_access_branch(
                        locked, branch
                    )
                ):
                    locked.active_branch_id = None
                    _save_workspace_pointers(locked, user, ["active_branch_id"])
                    WorkspaceBusinessLogicLayer.activate_workspace(
                        user, tenant_id, persist_preference=True
                    )
            else:
                WorkspaceBusinessLogicLayer.activate_workspace(
                    user, tenant_id, persist_preference=True
                )
            return

        if len(valid_ids) == 1:
            sole_tenant_id = next(iter(valid_ids))
            WorkspaceBusinessLogicLayer.activate_workspace(
                user, sole_tenant_id, persist_preference=True
            )

    @staticmethod
    def validate_active_branch_consistency(user: User) -> None:
        if not user.active_branch_id:
            return
        if not user.active_tenant_id:
            _raise_active_branch_tenant_mismatch(
                user=user,
                requested_branch_id=user.active_branch_id,
                resolved_branch=user.active_branch,
                raise_source="validate_active_branch_missing_tenant",
            )
        if not _same_uuid(user.active_branch.tenant_id, user.active_tenant_id):
            _raise_active_branch_tenant_mismatch(
                user=user,
                requested_branch_id=user.active_branch_id,
                resolved_branch=user.active_branch,
                raise_source="validate_active_branch_tenant_mismatch",
            )

    @staticmethod
    @transaction.atomic
    def set_active_branch(user: User, branch: Branch) -> None:
        WorkspaceBusinessLogicLayer.activate_workspace(
            user,
            branch.tenant_id,
            branch_id=branch.id,
            persist_preference=True,
        )

    @staticmethod
    def clear_active_branch_for_other_tenant(user: User, tenant_id) -> None:
        if not user.active_branch_id:
            return
        if not _same_uuid(user.active_branch.tenant_id, tenant_id):
            user.active_branch_id = None
            user.save(update_fields=["active_branch_id"])

    @staticmethod
    def clear_workspace_if_tenant(user: User, tenant_id) -> None:
        """
        Clear active tenant/branch when the user loses access to ``tenant_id``.
        """
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            coerced_tenant_id = _coerce_uuid(tenant_id)

            WorkspaceBusinessLogicLayer.delete_preferred_branch_for_tenant(
                locked, coerced_tenant_id
            )

            if not _same_uuid(locked.active_tenant_id, coerced_tenant_id):
                if locked.active_branch_id and _same_uuid(
                    locked.active_branch.tenant_id, coerced_tenant_id
                ):
                    locked.active_branch_id = None
                    locked.save(update_fields=["active_branch_id"])
                    user.active_branch_id = None
                return

            locked.active_tenant_id = None
            locked.active_branch_id = None
            locked.save(update_fields=["active_tenant_id", "active_branch_id"])
            user.active_tenant_id = None
            user.active_branch_id = None

    @staticmethod
    def assign_active_branch_for_first_tenant_branch(tenant, branch: Branch) -> None:
        """Assign the new branch to users on this tenant who have no active branch."""
        User.objects.filter(
            active_tenant_id=tenant.id,
            active_branch__isnull=True,
        ).update(active_branch_id=branch.id)
        preferences = UserTenantPreference.objects.filter(
            tenant_id=tenant.id,
            preferred_branch__isnull=True,
            user__active_tenant_id=tenant.id,
        )
        for preference in preferences:
            WorkspaceBusinessLogicLayer.persist_preferred_branch(
                preference.user, tenant.id, branch.id
            )

    @staticmethod
    def reassign_active_branch_after_deletion(deleted_branch: Branch) -> None:
        """Repoint active workspace and preferences that referenced the deleted branch."""
        tenant_id = deleted_branch.tenant_id
        user_ids_active = list(
            User.objects.filter(active_branch_id=deleted_branch.id).values_list(
                "id", flat=True
            )
        )
        preference_user_ids = list(
            UserTenantPreference.objects.filter(
                tenant_id=tenant_id,
                preferred_branch_id=deleted_branch.id,
            ).values_list("user_id", flat=True)
        )

        for user_id in set(user_ids_active) | set(preference_user_ids):
            user = User.objects.get(pk=user_id)
            if _same_uuid(user.active_tenant_id, tenant_id):
                WorkspaceBusinessLogicLayer.activate_workspace(
                    user, tenant_id, persist_preference=True
                )
            else:
                fallback = WorkspaceBusinessLogicLayer._resolve_fallback_branch(
                    user, tenant_id
                )
                if fallback is not None:
                    WorkspaceBusinessLogicLayer.persist_preferred_branch(
                        user, tenant_id, fallback.id
                    )
                else:
                    UserTenantPreference.objects.filter(
                        user_id=user_id,
                        tenant_id=tenant_id,
                    ).update(preferred_branch_id=None)

    @staticmethod
    def switch_active_branch(user: User, branch_id) -> None:
        branch = (
            Branch.objects.filter(id=_coerce_uuid(branch_id))
            .select_related("tenant")
            .first()
        )
        if branch is None:
            raise BranchNotFoundException()

        from access.services.membership_bll import membership_service

        valid_ids = membership_service.get_valid_tenant_ids(user)
        if str(branch.tenant_id) not in valid_ids:
            raise NotAMemberOfBranchException()

        WorkspaceBusinessLogicLayer.activate_workspace(
            user,
            branch.tenant_id,
            branch_id=branch.id,
            persist_preference=True,
        )


workspace_bll = WorkspaceBusinessLogicLayer()
