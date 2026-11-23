from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from access.constants import MembershipStatus
from access.models import (
    AssignmentStatus,
    PermissionOverride,
    StaffAssignment,
    StaffMembership,
)
from accounts.models import User
from access.selectors import membership_selector
from access.services.assignment_bll import assignment_bll
from access.services.permission_audit_bll import permission_audit_bll
from access.services.permission_override_bll import permission_override_bll
from access.services.rbac_bll import rbac_bll
from accounts.services.workspace_bll import workspace_bll
from core.exceptions import (
    StaffAssignmentNotFoundException,
    StaffMembershipNotFoundException,
    NotAMemberOfTenantException
)


class MembershipBusinessLogicLayer:
    @staticmethod
    def _schedule_effective_permissions_invalidation(membership: StaffMembership) -> None:
        """Bust effective-permissions cache after the surrounding txn commits."""
        user_id = membership.user_id
        tenant_id = membership.tenant_id

        def _invalidate():
            rbac_bll.invalidate_effective_permissions_cache(
                user_id=user_id,
                tenant_id=tenant_id,
            )

        transaction.on_commit(_invalidate)

    @staticmethod
    def _notify_member(membership: StaffMembership, type_: str, *, actor_id=None) -> None:
        from notifications import events as notification_events

        actor = User.objects.filter(pk=actor_id or membership.invited_by_id).first() if (actor_id or membership.invited_by_id) else None
        notification_events.staff_membership_changed(membership, type_, actor=actor)

    def create_membership(
        self,
        *,
        tenant_id,
        user_id,
        invited_by_id=None,
        status: str = MembershipStatus.PENDING,
    ) -> StaffMembership:
        try:
            with transaction.atomic():
                existing = (
                    StaffMembership.objects.select_for_update()
                    .filter(tenant_id=tenant_id, user_id=user_id)
                    .first()
                )
                if existing is not None:
                    if existing.status == MembershipStatus.REMOVED:
                        if invited_by_id is not None:
                            existing.invited_by_id = invited_by_id
                        if existing.joined_at is None:
                            existing.joined_at = timezone.now()
                        # Re-invitation restores the same row; prior assignments stay revoked.
                        existing.status = MembershipStatus.ACTIVE
                        existing.save(
                            update_fields=["status", "invited_by", "joined_at", "updated_at"]
                        )
                        self._schedule_effective_permissions_invalidation(existing)
                        self._notify_member(existing, "staff_created")
                        return existing
                    raise ValidationError(
                        {"user_id": "This user already has a membership for this tenant."}
                    )

                membership = StaffMembership.objects.create(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    invited_by_id=invited_by_id,
                    status=status,
                    joined_at=timezone.now() if status == MembershipStatus.ACTIVE else None,
                )
                self._schedule_effective_permissions_invalidation(membership)
                self._notify_member(membership, "staff_created")
                return membership
        except IntegrityError as exc:
            raise ValidationError(
                {"user_id": "This user already has a membership for this tenant."}
            ) from exc

    def update_membership(self, *, tenant_id, membership_id, **fields) -> StaffMembership:
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id
        )

        previous_status = membership.status
        if "status" in fields:
            new_status = fields["status"]
            if new_status == MembershipStatus.ACTIVE and membership.joined_at is None:
                membership.joined_at = timezone.now()
            membership.status = new_status

        self._full_clean_membership_or_raise(membership)

        with transaction.atomic():
            membership.save()
            self._schedule_effective_permissions_invalidation(membership)
            if membership.status != previous_status and membership.status == MembershipStatus.SUSPENDED:
                self._notify_member(membership, "staff_suspended")

        return membership

    def remove_membership(
        self, *, tenant_id, membership_id, actor_id=None
    ) -> StaffMembership:
        """Soft-remove a membership and revoke non-terminal assignments.

        Idempotent: already-removed memberships are returned unchanged.
        StaffAssignment rows and locations are never physically deleted.
        """
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id, lock=True
        )

        if membership.status == MembershipStatus.REMOVED:
            return membership

        with transaction.atomic():
            membership.status = MembershipStatus.REMOVED
            membership.save(update_fields=["status", "updated_at"])
            permission_audit_bll.record_membership_removed(
                membership=membership, actor_id=actor_id
            )
            self._revoke_non_terminal_assignments(
                membership=membership, actor_id=actor_id
            )
            self._remove_permission_overrides(
                membership=membership, actor_id=actor_id
            )
            workspace_bll.delete_preferred_branch_for_tenant(
                membership.user, membership.tenant_id
            )
            User.objects.filter(
                pk=membership.user_id,
                active_tenant_id=membership.tenant_id,
            ).update(active_tenant_id=None, active_branch_id=None)
            self._schedule_effective_permissions_invalidation(membership)
            self._notify_member(membership, "staff_removed", actor_id=actor_id)

        return membership

    def restore_membership(self, *, tenant_id, membership_id) -> StaffMembership:
        """Re-activate a removed membership. Does not un-revoke assignments."""
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id, lock=True
        )
        if membership.status != MembershipStatus.REMOVED:
            return membership

        if membership.joined_at is None:
            membership.joined_at = timezone.now()
        membership.status = MembershipStatus.ACTIVE
        with transaction.atomic():
            membership.save(update_fields=["status", "joined_at", "updated_at"])
            self._schedule_effective_permissions_invalidation(membership)
        return membership

    def _revoke_non_terminal_assignments(self, *, membership, actor_id=None) -> None:
        assignments = StaffAssignment.objects.filter(
            membership_id=membership.id,
            status__in=[AssignmentStatus.ACTIVE, AssignmentStatus.FUTURE],
        )
        for assignment in assignments:
            assignment_bll.revoke_assignment(
                assignment_id=assignment.id,
                revoked_by_id=actor_id,
            )

    def _remove_permission_overrides(self, *, membership, actor_id=None) -> None:
        override_ids = list(
            PermissionOverride.objects.filter(membership_id=membership.id).values_list(
                "id", flat=True
            )
        )
        for override_id in override_ids:
            permission_override_bll.delete_override(
                tenant_id=membership.tenant_id,
                override_id=override_id,
                actor_id=actor_id,
            )

    def _get_membership_in_tenant_or_raise(
        self, *, tenant_id, membership_id, lock: bool = False
    ) -> StaffMembership:
        queryset = StaffMembership.objects.filter(
            id=membership_id, tenant_id=tenant_id
        )
        if lock:
            queryset = queryset.select_for_update()
        membership = queryset.first()
        if membership is None:
            raise StaffMembershipNotFoundException()
        return membership

    def create_assignment(
        self,
        *,
        membership_id,
        role_id,
        location_ids=None,
        all_locations=False,
        mode=None,
        valid_from=None,
        valid_until=None,
        granted_by_id=None,
        branch_id=None,
    ) -> StaffAssignment:
        resolved_location_ids = location_ids
        resolved_all_locations = all_locations
        if branch_id is not None:
            resolved_location_ids = [branch_id]
            resolved_all_locations = False
        return assignment_bll.create_assignment(
            membership_id=membership_id,
            role_id=role_id,
            branch_ids=resolved_location_ids,
            all_locations=resolved_all_locations,
            mode=mode,
            valid_from=valid_from,
            valid_until=valid_until,
            granted_by_id=granted_by_id,
        )

    def update_assignment(self, *, tenant_id, assignment_id, updated_by_id=None, **fields) -> StaffAssignment:
        self._get_assignment_in_tenant_or_raise(
            tenant_id=tenant_id, assignment_id=assignment_id
        )
        update_kwargs = {}
        field_map = {
            "role_id": "role_id",
            "location_ids": "branch_ids",
            "all_locations": "all_locations",
            "mode": "mode",
            "valid_from": "valid_from",
            "valid_until": "valid_until",
        }
        for api_field, bll_field in field_map.items():
            if api_field in fields:
                update_kwargs[bll_field] = fields[api_field]
        if updated_by_id is not None:
            update_kwargs["updated_by_id"] = updated_by_id
        return assignment_bll.update_assignment(assignment_id=assignment_id, **update_kwargs)

    def revoke_assignment(self, *, tenant_id, assignment_id, revoked_by_id) -> StaffAssignment:
        self._get_assignment_in_tenant_or_raise(
            tenant_id=tenant_id, assignment_id=assignment_id
        )
        return assignment_bll.revoke_assignment(
            assignment_id=assignment_id,
            revoked_by_id=revoked_by_id,
        )

    def delete_assignment(self, *, tenant_id, assignment_id, revoked_by_id=None) -> StaffAssignment:
        return self.revoke_assignment(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            revoked_by_id=revoked_by_id,
        )

    @staticmethod
    def get_membership_data(user) -> list[dict]:
        """Same shape used by UserMeOutputSerializer — owner + active staff memberships."""
        data = []

        owner_profile = None
        try:
            owner_profile = user.owner_profile
        except ObjectDoesNotExist:
            owner_profile = None

        if owner_profile:
            tenants = owner_profile.tenants.all()
            for tenant in tenants:
                data.append({"tenant": tenant, "is_owner": True})

        # A platform superuser can work in any business. The one they opened
        # (active tenant) is listed like an owned one, flagged platform_access,
        # so the owner console works for it without a real membership.
        if (
            getattr(user, "is_superuser", False)
            and getattr(user, "is_active", False)
            and getattr(user, "active_tenant_id", None)
            and not any(str(m["tenant"].id) == str(user.active_tenant_id) for m in data)
        ):
            from tenants.models import Tenant

            tenant = Tenant.objects.filter(id=user.active_tenant_id).first()
            if tenant is not None:
                data.append({"tenant": tenant, "is_owner": True, "platform_access": True})

        for sm in membership_selector.get_active_staff_memberships(user=user):
            if (
                hasattr(sm, "_prefetched_objects_cache")
                and "assignments" in sm._prefetched_objects_cache
            ):
                assignments = sm.assignments.all()
            else:
                assignments = membership_selector.get_assignments_for_membership(
                    membership=sm
                )
            data.append({
                "tenant": sm.tenant,
                "is_owner": False,
                "staff_membership": sm,
                "assignments": assignments,
            })

        return data

    @staticmethod
    def get_valid_tenant_ids(user) -> set[str]:
        return {
            str(m["tenant"].id)
            for m in MembershipBusinessLogicLayer.get_membership_data(user)
        }

    @staticmethod
    def switch_active_tenant(user, tenant_id: str) -> None:
        workspace_bll.activate_workspace(user, tenant_id, persist_preference=True)

    @staticmethod
    def switch_active_branch(user, branch_id: str) -> None:
        workspace_bll.switch_active_branch(user, branch_id)

    def _get_membership_or_raise(self, *, membership_id) -> StaffMembership:
        try:
            return StaffMembership.objects.get(id=membership_id)
        except StaffMembership.DoesNotExist as exc:
            raise ValidationError({"membership_id": "Staff membership not found."}) from exc

    def _get_assignment_in_tenant_or_raise(self, *, tenant_id, assignment_id) -> StaffAssignment:
        try:
            return StaffAssignment.objects.get(id=assignment_id, membership__tenant_id=tenant_id)
        except StaffAssignment.DoesNotExist as exc:
            raise StaffAssignmentNotFoundException() from exc

    def _full_clean_membership_or_raise(self, membership: StaffMembership) -> None:
        try:
            membership.full_clean()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc


membership_service = MembershipBusinessLogicLayer()