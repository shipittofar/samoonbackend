from __future__ import annotations

import logging
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from accounts.models import User
from access.services.assignment_scope import (
    filter_assignments_for_authorization,
    membership_covers_branch,
)
from core.exceptions import (
    ActiveBranchTenantMismatchException,
    BranchNotFoundException,
    NotAMemberOfBranchException,
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
    def validate_active_branch_consistency(user: User) -> None:
        """
        Defensive consistency check. Not currently called from the
        switch-branch API chain; instrumented so any future caller is
        identifiable via raise_source.
        """
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
        # Always re-read under row lock so concurrent switch-tenant /
        # ownership-transfer cannot leave us comparing against a stale
        # request.user.active_tenant_id.
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.active_tenant_id:
            _raise_active_branch_tenant_mismatch(
                user=locked,
                requested_branch_id=branch.id,
                resolved_branch=branch,
                raise_source="set_active_branch_missing_active_tenant",
            )
        if not _same_uuid(locked.active_tenant_id, branch.tenant_id):
            _raise_active_branch_tenant_mismatch(
                user=locked,
                requested_branch_id=branch.id,
                resolved_branch=branch,
                raise_source="set_active_branch_tenant_id_mismatch",
            )
        if not WorkspaceBusinessLogicLayer.user_can_access_branch(locked, branch):
            raise NotAMemberOfBranchException()

        locked.active_branch = branch
        # Enforce only the workspace invariant here. Model.full_clean() also
        # validates unrelated fields (email uniqueness, etc.) and previously
        # remapped ANY ValidationError to active_branch_tenant_mismatch even
        # when active_tenant_id == branch.tenant_id (Case A false positive).
        try:
            locked.clean()
        except DjangoValidationError as exc:
            message_dict = getattr(exc, "message_dict", {}) or {}
            if "active_branch" in message_dict or "active_tenant" in message_dict:
                _raise_active_branch_tenant_mismatch(
                    user=locked,
                    requested_branch_id=branch.id,
                    resolved_branch=branch,
                    raise_source="user_clean_workspace_validation",
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
                "Unexpected User.clean ValidationError during set_active_branch "
                "with matching tenant/branch ids; not remapping to "
                "active_branch_tenant_mismatch",
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
        locked.save(update_fields=["active_branch_id"])
        user.active_branch_id = locked.active_branch_id
        user.active_tenant_id = locked.active_tenant_id

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

        Branches themselves stay on ``Branch.tenant_id``; only the user's
        workspace pointers are cleared.

        Locks the user row so concurrent switch-tenant / switch-branch cannot
        repopulate a workspace the caller is clearing (e.g. ownership transfer).
        """
        with transaction.atomic():
            # No select_related on nullable FKs — PostgreSQL rejects
            # FOR UPDATE with outer joins.
            locked = User.objects.select_for_update().get(pk=user.pk)
            coerced_tenant_id = _coerce_uuid(tenant_id)

            if not _same_uuid(locked.active_tenant_id, coerced_tenant_id):
                # Stale/inconsistent: branch points at transferred tenant, tenant does not.
                if locked.active_branch_id and _same_uuid(
                    locked.active_branch.tenant_id, coerced_tenant_id
                ):
                    locked.active_branch_id = None
                    locked.save(update_fields=["active_branch_id"])
                    user.active_branch_id = None
                return

            # active_tenant is the transferred tenant — clear both pointers.
            # Even if active_branch belonged to another tenant (inconsistent),
            # active_branch cannot remain without an active_tenant.
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

    @staticmethod
    def reassign_active_branch_after_deletion(deleted_branch: Branch) -> None:
        """Repoint users whose active branch was deleted to a sibling or NULL."""
        replacement = (
            Branch.objects.filter(tenant_id=deleted_branch.tenant_id)
            .exclude(id=deleted_branch.id)
            .order_by("-is_default", "created_at")
            .first()
        )
        User.objects.filter(active_branch_id=deleted_branch.id).update(
            active_branch_id=replacement.id if replacement else None,
        )

    @staticmethod
    def switch_active_branch(user: User, branch_id) -> None:
        branch = (
            Branch.objects.filter(id=_coerce_uuid(branch_id))
            .select_related("tenant")
            .first()
        )
        if branch is None:
            raise BranchNotFoundException()
        WorkspaceBusinessLogicLayer.set_active_branch(user, branch)


workspace_bll = WorkspaceBusinessLogicLayer()
