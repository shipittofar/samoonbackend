from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from access.authorization.admin_role_protection import assert_role_assignable_by_actor
from access.models import (
    AssignmentMode,
    AssignmentStatus,
    Role,
    StaffAssignment,
    StaffAssignmentLocation,
    StaffMembership,
)
from access.services.permission_audit_bll import permission_audit_bll
from access.services.rbac_bll import rbac_bll
from tenants.models import Branch

_UNSET = object()


class AssignmentBusinessLogicLayer:
    """Canonical StaffAssignment writes — one row per role grant, M2M locations."""

    def create_assignment(
        self,
        *,
        membership_id,
        role_id,
        branch_id=None,
        branch_ids: list | None = None,
        all_locations: bool | None = None,
        mode: str | None = None,
        valid_from=None,
        valid_until=None,
        granted_by_id=None,
    ) -> StaffAssignment:
        membership = self._get_membership_or_raise(membership_id=membership_id)
        role = self._get_role_or_raise(role_id=role_id)
        if granted_by_id is not None:
            from accounts.models import User

            actor = User.objects.filter(id=granted_by_id).first()
            if actor is not None:
                assert_role_assignable_by_actor(role=role, actor=actor)

        resolved_branch_ids, resolved_all_locations = self._resolve_location_scope(
            membership=membership,
            branch_id=branch_id,
            branch_ids=branch_ids,
            all_locations=all_locations,
        )

        assignment = StaffAssignment(
            membership=membership,
            role=role,
            all_locations=resolved_all_locations,
            mode=mode or AssignmentMode.MANAGE,
            valid_from=valid_from,
            valid_until=valid_until,
            granted_by_id=granted_by_id,
            granted_at=timezone.now() if granted_by_id else None,
        )
        self._full_clean_or_raise(assignment)

        try:
            with transaction.atomic():
                assignment.save()
                self._sync_scope_after_save(
                    assignment=assignment,
                    resolved_all_locations=resolved_all_locations,
                    resolved_branch_ids=resolved_branch_ids,
                )
                if granted_by_id:
                    permission_audit_bll.record_assignment_created(
                        assignment=assignment,
                        actor_id=granted_by_id,
                    )
        except IntegrityError as exc:
            raise ValidationError(
                {
                    "non_field_errors": (
                        "This membership already has an active assignment for this role."
                    )
                }
            ) from exc

        assignment = self._reload_assignment(assignment.id)
        rbac_bll.invalidate_effective_permissions_for_membership(assignment.membership)
        return assignment

    def update_assignment(
        self,
        *,
        assignment_id,
        role_id=_UNSET,
        branch_ids=_UNSET,
        all_locations=_UNSET,
        mode=_UNSET,
        valid_from=_UNSET,
        valid_until=_UNSET,
        updated_by_id=None,
    ) -> StaffAssignment:
        assignment = self._get_assignment_or_raise(assignment_id=assignment_id)
        self._ensure_mutable(assignment)

        membership = assignment.membership

        if role_id is not _UNSET:
            new_role = self._get_role_or_raise(role_id=role_id)
            if updated_by_id is not None:
                from accounts.models import User

                actor = User.objects.filter(id=updated_by_id).first()
                if actor is not None:
                    assert_role_assignable_by_actor(role=new_role, actor=actor)
            assignment.role = new_role

        if mode is not _UNSET:
            assignment.mode = mode

        if valid_from is not _UNSET:
            assignment.valid_from = valid_from

        if valid_until is not _UNSET:
            assignment.valid_until = valid_until

        scope_update = branch_ids is not _UNSET or all_locations is not _UNSET
        if scope_update:
            effective_all = (
                all_locations if all_locations is not _UNSET else assignment.all_locations
            )
            if branch_ids is not _UNSET:
                effective_ids = branch_ids
            else:
                effective_ids = list(
                    assignment.locations.values_list("branch_id", flat=True)
                )

            resolved_branch_ids, resolved_all_locations = self._resolve_location_scope(
                membership=membership,
                branch_id=None,
                branch_ids=effective_ids,
                all_locations=effective_all,
            )
            assignment.all_locations = resolved_all_locations
        else:
            resolved_all_locations = assignment.all_locations
            resolved_branch_ids = None

        self._full_clean_or_raise(assignment)

        try:
            with transaction.atomic():
                assignment.save()
                if scope_update:
                    if resolved_all_locations:
                        StaffAssignmentLocation.objects.filter(
                            assignment_id=assignment.id
                        ).delete()
                    else:
                        self._sync_assignment_locations(
                            assignment=assignment,
                            branch_ids=resolved_branch_ids or [],
                        )
                if updated_by_id:
                    permission_audit_bll.record_assignment_updated(
                        assignment=assignment,
                        actor_id=updated_by_id,
                    )
        except IntegrityError as exc:
            raise ValidationError(
                {
                    "non_field_errors": (
                        "This membership already has an active assignment for this role."
                    )
                }
            ) from exc

        assignment = self._reload_assignment(assignment.id)
        rbac_bll.invalidate_effective_permissions_for_membership(assignment.membership)
        return assignment

    def revoke_assignment(self, *, assignment_id, revoked_by_id) -> StaffAssignment:
        assignment = self._get_assignment_or_raise(assignment_id=assignment_id)

        if assignment.status == AssignmentStatus.REVOKED:
            return self._reload_assignment(assignment.id)

        assignment.status = AssignmentStatus.REVOKED
        assignment.revoked_by_id = revoked_by_id
        assignment.revoked_at = timezone.now()

        with transaction.atomic():
            assignment.save(
                update_fields=["status", "revoked_by_id", "revoked_at", "updated_at"]
            )
            permission_audit_bll.record_assignment_revoked(
                assignment=assignment,
                actor_id=revoked_by_id,
            )

        assignment = self._reload_assignment(assignment.id)
        rbac_bll.invalidate_effective_permissions_for_membership(assignment.membership)
        return assignment

    @staticmethod
    def _sync_scope_after_save(
        *,
        assignment: StaffAssignment,
        resolved_all_locations: bool,
        resolved_branch_ids: list,
    ) -> None:
        if resolved_all_locations:
            StaffAssignmentLocation.objects.filter(assignment_id=assignment.id).delete()
        else:
            AssignmentBusinessLogicLayer._sync_assignment_locations(
                assignment=assignment,
                branch_ids=resolved_branch_ids,
            )

    @staticmethod
    def _resolve_location_scope(
        *,
        membership: StaffMembership,
        branch_id,
        branch_ids: list | None,
        all_locations: bool | None,
    ) -> tuple[list, bool]:
        if branch_ids is not None:
            normalized = AssignmentBusinessLogicLayer._normalize_branch_ids(
                membership=membership,
                branch_ids=branch_ids,
            )
            if all_locations is True and normalized:
                raise ValidationError(
                    {
                        "location_ids": (
                            "Must be empty when all_locations is true."
                        )
                    }
                )
            if all_locations is True or not normalized:
                return [], True
            return normalized, False

        if branch_id is not None:
            return (
                AssignmentBusinessLogicLayer._normalize_branch_ids(
                    membership=membership,
                    branch_ids=[branch_id],
                ),
                False,
            )

        if all_locations is False:
            raise ValidationError(
                {
                    "location_ids": (
                        "At least one location_id is required when all_locations is false."
                    )
                }
            )

        return [], True

    @staticmethod
    def _normalize_branch_ids(*, membership: StaffMembership, branch_ids: list) -> list:
        if not branch_ids:
            return []

        normalized: list = []
        seen: set = set()
        for raw_id in branch_ids:
            branch = Branch.objects.filter(id=raw_id, tenant_id=membership.tenant_id).first()
            if branch is None:
                raise ValidationError(
                    {"location_ids": f"Location '{raw_id}' not found for this tenant."}
                )
            if branch.id not in seen:
                seen.add(branch.id)
                normalized.append(branch.id)
        return normalized

    @staticmethod
    def _sync_assignment_locations(*, assignment: StaffAssignment, branch_ids: list) -> None:
        desired = set(branch_ids)
        existing = set(
            assignment.locations.values_list("branch_id", flat=True)
        )

        to_remove = existing - desired
        if to_remove:
            StaffAssignmentLocation.objects.filter(
                assignment_id=assignment.id,
                branch_id__in=to_remove,
            ).delete()

        to_add = desired - existing
        StaffAssignmentLocation.objects.bulk_create(
            [
                StaffAssignmentLocation(assignment_id=assignment.id, branch_id=branch_id)
                for branch_id in to_add
            ]
        )

    def _get_membership_or_raise(self, *, membership_id) -> StaffMembership:
        try:
            return StaffMembership.objects.select_related("tenant").get(id=membership_id)
        except StaffMembership.DoesNotExist as exc:
            raise ValidationError({"membership_id": "Staff membership not found."}) from exc

    def _get_role_or_raise(self, *, role_id) -> Role:
        try:
            return Role.objects.get(id=role_id)
        except Role.DoesNotExist as exc:
            raise ValidationError({"role_id": "Role not found."}) from exc

    def _get_assignment_or_raise(self, *, assignment_id) -> StaffAssignment:
        try:
            return StaffAssignment.objects.select_related("membership__tenant").get(
                id=assignment_id
            )
        except StaffAssignment.DoesNotExist as exc:
            raise ValidationError({"assignment_id": "Staff assignment not found."}) from exc

    @staticmethod
    def _ensure_mutable(assignment: StaffAssignment) -> None:
        if assignment.status == AssignmentStatus.REVOKED:
            raise ValidationError({"status": "Cannot update a revoked assignment."})

    @staticmethod
    def _reload_assignment(assignment_id) -> StaffAssignment:
        return (
            StaffAssignment.objects.select_related(
                "role",
                "membership",
                "membership__user",
                "granted_by",
                "revoked_by",
            )
            .prefetch_related("locations__branch")
            .get(id=assignment_id)
        )

    @staticmethod
    def _full_clean_or_raise(assignment: StaffAssignment) -> None:
        try:
            assignment.full_clean()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc


assignment_bll = AssignmentBusinessLogicLayer()
