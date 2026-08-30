from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from access.constants import MembershipStatus
from access.models import StaffAssignment, StaffMembership
from accounts.models import User
from access.selectors import membership_selector
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
from accounts.services.workspace_bll import workspace_bll
from core.exceptions import (
    StaffAssignmentNotFoundException,
    StaffMembershipAlreadyRemovedException,
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
                membership = StaffMembership.objects.create(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    invited_by_id=invited_by_id,
                    status=status,
                    joined_at=timezone.now() if status == MembershipStatus.ACTIVE else None,
                )
                self._schedule_effective_permissions_invalidation(membership)
                return membership
        except IntegrityError as exc:
            raise ValidationError(
                {"user_id": "This user already has a membership for this tenant."}
            ) from exc

    def update_membership(self, *, tenant_id, membership_id, **fields) -> StaffMembership:
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id
        )

        if "status" in fields:
            new_status = fields["status"]
            if new_status == MembershipStatus.ACTIVE and membership.joined_at is None:
                membership.joined_at = timezone.now()
            membership.status = new_status

        self._full_clean_membership_or_raise(membership)

        with transaction.atomic():
            membership.save()
            self._schedule_effective_permissions_invalidation(membership)

        return membership

    def remove_membership(self, *, tenant_id, membership_id) -> StaffMembership:
        membership = self._get_membership_in_tenant_or_raise(
            tenant_id=tenant_id, membership_id=membership_id
        )

        if membership.status == MembershipStatus.REMOVED:
            raise StaffMembershipAlreadyRemovedException()

        with transaction.atomic():
            membership.status = MembershipStatus.REMOVED
            membership.save(update_fields=["status", "updated_at"])
            workspace_bll.delete_preferred_branch_for_tenant(
                membership.user, membership.tenant_id
            )
            User.objects.filter(
                pk=membership.user_id,
                active_tenant_id=membership.tenant_id,
            ).update(active_tenant_id=None, active_branch_id=None)
            self._schedule_effective_permissions_invalidation(membership)

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

    def _get_membership_in_tenant_or_raise(self, *, tenant_id, membership_id) -> StaffMembership:
        try:
            return StaffMembership.objects.get(id=membership_id, tenant_id=tenant_id)
        except StaffMembership.DoesNotExist as exc:
            raise StaffMembershipNotFoundException() from exc

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