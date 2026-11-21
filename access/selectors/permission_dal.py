from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from access.services.assignment_scope import (
    filter_assignments_for_authorization,
    filter_assignments_in_scope,
)
from access.authorization.admin_role_protection import (
    filter_assignments_queryset_for_viewer,
    filter_roles_queryset_for_viewer,
    is_protected_admin_role,
    viewer_may_see_admin_role,
)
from access.constants import MembershipStatus
from access.constants.tenant_eligibility import is_tenant_rbac_eligible
from access.models import (
    Permission,
    Role,
    RolePermission,
    StaffAssignment,
    StaffMembership,
    StaffMembershipStatus,
)
from tenants.models import (
    Tenant,
)


class PermissionDataAccessLayer:
    """Read-only queries around roles/permissions/staff scope resolution."""

    def get_active_membership(self, *, user_id, tenant_id) -> StaffMembership | None:
        return StaffMembership.objects.filter(
            user_id=user_id,
            tenant_id=tenant_id,
            status=MembershipStatus.ACTIVE,
        ).first()

    def get_assignments_in_scope(self, *, membership_id, branch_id=None) -> QuerySet[StaffAssignment]:
        queryset = filter_assignments_for_authorization(
            StaffAssignment.objects.filter(membership_id=membership_id)
        ).select_related("role").prefetch_related("locations")
        return filter_assignments_in_scope(queryset, branch_id=branch_id)

    def get_permission_slugs_for_roles(self, *, role_ids) -> set[str]:
        if not role_ids:
            return set()

        return set(
            RolePermission.objects.filter(role_id__in=role_ids)
            .values_list("permission__slug", flat=True)
        )

    def get_user_permission_slugs(self, *, user_id, tenant_id, branch_id=None) -> set[str]:
        """Internal DAL helper — prefer rbac_bll.get_effective_permissions() for resolution."""
        from accounts.models import User
        from access.authorization.platform import is_platform_superuser

        user = User.objects.filter(id=user_id).first()
        if user is None:
            return set()

        tenant = Tenant.objects.filter(id=tenant_id).select_related("owner").first()
        if tenant is None:
            return set()
        # Superusers hold every permission even in a closed/inactive tenant.
        if not is_tenant_rbac_eligible(tenant) and not is_platform_superuser(user):
            return set()

        from access.services.rbac_bll import rbac_bll

        return rbac_bll.resolve_effective_permission_slugs(
            user=user,
            tenant=tenant,
            branch_id=branch_id,
        )

    def user_has_permissions(
        self, *, user_id, tenant_id, branch_id=None, permission_slugs, require_all=True
    ) -> bool:
        granted = self.get_user_permission_slugs(
            user_id=user_id, tenant_id=tenant_id, branch_id=branch_id
        )

        if require_all:
            return all(slug in granted for slug in permission_slugs)
        return any(slug in granted for slug in permission_slugs)

    def user_has_manage_roles_permission(self, *, user_id) -> bool:
        from accounts.models import User

        user = User.objects.filter(id=user_id).first()
        if user is None:
            return False

        from access.services.rbac_bll import rbac_bll
        from tenants.models import Tenant

        tenant_ids: set = set(
            Tenant.objects.filter(owner__user_id=user_id).values_list("id", flat=True)
        )
        tenant_ids.update(
            StaffMembership.objects.filter(
                user_id=user_id,
                status=StaffMembershipStatus.ACTIVE,
            ).values_list("tenant_id", flat=True)
        )

        for tenant_id in tenant_ids:
            tenant = Tenant.objects.select_related("owner").filter(id=tenant_id).first()
            if tenant is None:
                continue
            granted = rbac_bll.resolve_effective_permission_slugs(
                user=user,
                tenant=tenant,
            )
            if "rbac.manage_roles" in granted:
                return True
        return False

    def get_permissions_by_slugs(self, *, slugs) -> QuerySet[Permission]:
        return Permission.objects.filter(slug__in=slugs)


class RoleDataAccessLayer:
    """Read-only queries for role/permission admin listing endpoints."""

    def get_role_queryset(self, *, viewer=None) -> QuerySet[Role]:
        return filter_roles_queryset_for_viewer(Role.objects.all(), viewer)

    def get_role_by_id(self, *, role_id, viewer=None) -> Role | None:
        role = Role.objects.filter(id=role_id).first()
        if role is None:
            return None
        if is_protected_admin_role(role=role) and not viewer_may_see_admin_role(viewer):
            return None
        return role

    def get_permission_queryset(self) -> QuerySet[Permission]:
        return Permission.objects.all()

    def get_permission_by_id(self, *, permission_id) -> Permission | None:
        return Permission.objects.filter(id=permission_id).first()


class StaffDataAccessLayer:
    """Read-only queries for staff membership / assignment admin endpoints."""

    def get_membership_queryset(self, *, tenant_id) -> QuerySet[StaffMembership]:
        return (
            StaffMembership.objects.filter(tenant_id=tenant_id)
            .select_related("user", "tenant", "invited_by")
            .order_by("-created_at")
        )

    def get_membership_by_id(self, *, tenant_id, membership_id) -> StaffMembership | None:
        return (
            StaffMembership.objects.filter(tenant_id=tenant_id, id=membership_id)
            .select_related("user", "tenant", "invited_by")
            .first()
        )

    def get_assignment_queryset(
        self, *, tenant_id, membership_id=None, user_id=None, viewer=None
    ) -> QuerySet[StaffAssignment]:
        qs = (
            StaffAssignment.objects.filter(membership__tenant_id=tenant_id)
            .select_related(
                "role",
                "membership",
                "membership__tenant",
                "membership__user",
                "granted_by",
                "revoked_by",
            )
            .prefetch_related("locations__branch")
            .order_by("-created_at")
        )
        if membership_id is not None:
            qs = qs.filter(membership_id=membership_id)
        if user_id is not None:
            qs = qs.filter(membership__user_id=user_id)
        return filter_assignments_queryset_for_viewer(qs, viewer)

    def get_assignment_by_id(
        self, *, tenant_id, assignment_id, viewer=None
    ) -> StaffAssignment | None:
        assignment = (
            StaffAssignment.objects.filter(
                membership__tenant_id=tenant_id, id=assignment_id
            )
            .select_related(
                "role",
                "membership",
                "membership__tenant",
                "membership__user",
                "granted_by",
                "revoked_by",
            )
            .prefetch_related("locations__branch")
            .first()
        )
        if assignment is None:
            return None
        filtered = filter_assignments_queryset_for_viewer(
            StaffAssignment.objects.filter(id=assignment.id),
            viewer,
        )
        if not filtered.exists():
            return None
        return assignment


class MembershipDataAccessLayer:
    """Read-only queries for resolving a user's tenant memberships."""

    def get_owned_tenants(self, *, owner_profile) -> QuerySet[Tenant]:
        return owner_profile.tenants.all()

    def get_active_staff_memberships(self, *, user) -> QuerySet[StaffMembership]:
        assignments = StaffAssignment.objects.select_related("role").prefetch_related(
            "locations"
        )
        return (
            StaffMembership.objects
            .filter(user=user, status=StaffMembershipStatus.ACTIVE)
            .select_related("tenant")
            .prefetch_related(
                Prefetch("assignments", queryset=assignments),
            )
        )

    def get_assignments_for_membership(self, *, membership) -> QuerySet[StaffAssignment]:
        return membership.assignments.select_related("role").prefetch_related(
            "locations"
        )



permission_selector = PermissionDataAccessLayer()
role_selector = RoleDataAccessLayer()
staff_selector = StaffDataAccessLayer()
membership_selector = MembershipDataAccessLayer()