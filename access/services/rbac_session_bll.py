from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Prefetch
from rest_framework.exceptions import ValidationError

from accounts.models import User
from access.authorization.tenant_access import TenantOwnerChecker
from access.constants import MembershipStatus
from access.models import StaffAssignment, StaffMembership
from access.selectors import permission_selector
from access.services.membership_bll import membership_service
from access.services.rbac_bll import rbac_bll
from core.exceptions import (
    PermissionDeniedException,
    StaffMembershipNotFoundException,
)
from core.exceptions.tenant import TenantNotFoundException
from tenants.models import Tenant


class RbacSessionBusinessLogicLayer:
    def build_me(self, *, user, request) -> dict:
        from accounts.services.workspace_bll import workspace_bll

        user = self._load_user_for_me(user)
        workspace_bll.ensure_workspace_initialized(user)
        user = self._load_user_for_me(user)
        membership_data = membership_service.get_membership_data(user)

        active_membership = None
        if user.active_tenant_id:
            active_membership = {
                "tenantId": str(user.active_tenant_id),
                "branchId": (
                    str(user.active_branch_id) if user.active_branch_id else None
                ),
            }

        return {
            "user": self._build_user_block(user=user, request=request),
            "memberships": membership_data,
            "activeMembership": active_membership,
            "tenantRoles": rbac_bll.build_tenant_role_records(
                user, viewer=user
            ),
            "ownership": rbac_bll.build_ownership_records(user),
            "staffAssignments": rbac_bll.build_staff_assignment_records(
                user, viewer=user
            ),
        }

    def build_permissions(self, *, user, request) -> dict:
        tenant = rbac_bll.resolve_tenant_context(user=user, request=request)
        permissions = rbac_bll.get_effective_permissions(user=user, tenant=tenant)
        return {"permissions": permissions}

    def build_roles(self, *, tenant_id, user) -> list[dict]:
        tenant = (
            Tenant.objects.select_related("owner")
            .filter(id=tenant_id)
            .first()
        )
        if tenant is None:
            raise TenantNotFoundException(detail="No tenant with this id.")

        rbac_bll.assert_tenant_member(user=user, tenant=tenant)

        effective = set(rbac_bll.get_effective_permissions(user=user, tenant=tenant))
        if "staff.view" not in effective:
            raise PermissionDeniedException(
                detail="Requires staff.view for this tenant."
            )

        return rbac_bll.get_roles_with_permissions(viewer=user)

    def resolve_effective_permissions_subject(
        self,
        *,
        actor,
        tenant,
        membership_id=None,
        user_id=None,
    ) -> User:
        """
        Resolve whose effective permissions to compute for /auth/me/effective-permissions/.

        With no subject params → actor (self).
        With membership_id and/or user_id → that staff user in ``tenant`` (tenant-scoped).
        """
        membership_id = (str(membership_id).strip() if membership_id else None) or None
        user_id = (str(user_id).strip() if user_id else None) or None

        if membership_id is None and user_id is None:
            return actor

        membership = None
        if membership_id is not None:
            membership = (
                StaffMembership.objects.select_related("user")
                .filter(id=membership_id, tenant_id=tenant.id)
                .first()
            )
            if membership is None:
                # Same 404 for missing and cross-tenant — do not leak existence.
                raise StaffMembershipNotFoundException()

        if user_id is not None:
            if membership is not None:
                if str(membership.user_id) != str(user_id):
                    raise ValidationError(
                        {
                            "non_field_errors": (
                                "membership_id and user_id do not refer to the same staff member."
                            )
                        }
                    )
            else:
                membership = (
                    StaffMembership.objects.select_related("user")
                    .filter(
                        user_id=user_id,
                        tenant_id=tenant.id,
                        status=MembershipStatus.ACTIVE,
                    )
                    .first()
                )
                if membership is None:
                    raise StaffMembershipNotFoundException()

        subject = membership.user
        if str(subject.id) != str(actor.id):
            self._assert_can_inspect_staff_permissions(actor=actor, tenant=tenant)
        return subject

    @staticmethod
    def _assert_can_inspect_staff_permissions(*, actor, tenant) -> None:
        if TenantOwnerChecker().is_owner(user=actor, tenant_id=tenant.id):
            return
        if permission_selector.user_has_permissions(
            user_id=actor.id,
            tenant_id=tenant.id,
            permission_slugs=("staff.view", "staff.manage"),
            require_all=False,
        ):
            return
        raise PermissionDeniedException(
            detail="Requires staff.view or staff.manage to inspect another user's permissions."
        )

    @staticmethod
    def _load_user_for_me(user: User) -> User:
        active_staff = StaffMembership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
        )
        assignments = StaffAssignment.objects.select_related("role").prefetch_related(
            "locations"
        )
        return (
            User.objects.select_related("owner_profile", "active_tenant")
            .prefetch_related(
                "owner_profile__tenants",
                Prefetch(
                    "staff_memberships",
                    queryset=active_staff.select_related("tenant").prefetch_related(
                        Prefetch("assignments", queryset=assignments)
                    ),
                ),
            )
            .get(pk=user.pk)
        )

    @staticmethod
    def _build_user_block(*, user, request) -> dict:
        # Relative media URL — preserved for backward compatibility with pre-Phase-1 /auth/me.
        avatar = user.avatar.url if user.avatar else None

        has_owner_profile = False
        try:
            has_owner_profile = user.owner_profile is not None
        except ObjectDoesNotExist:
            has_owner_profile = False

        has_staff_membership = any(
            membership.status == MembershipStatus.ACTIVE
            for membership in user.staff_memberships.all()
        )

        return {
            "id": str(user.id),
            "email": user.email,
            "accountType": (
                "business" if has_owner_profile or has_staff_membership else "customer"
            ),
            "phone_number": user.phone_number or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "avatar": avatar,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
        }


rbac_session_bll = RbacSessionBusinessLogicLayer()
