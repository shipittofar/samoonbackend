"""Authorization must ignore revoked and expired assignments."""
import uuid

from django.test import TestCase

from access.models import (
    AssignmentStatus,
    Role,
    StaffMembership,
    StaffMembershipStatus,
)
from access.selectors.permission_dal import permission_selector
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
from accounts.models import User
from accounts.services.workspace_bll import workspace_bll
from tenants.models import Branch, Owner, Tenant, TenantStatus


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant(**kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return owner_user, tenant


class RevokedAssignmentAuthorizationTests(TestCase):
    def setUp(self):
        self.revoker, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(tenant=self.tenant, name="Branch A")
        self.branch_b = Branch.objects.create(tenant=self.tenant, name="Branch B")

    def _has_staff_view_at_branch(self, branch):
        slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=branch.id,
        )
        return "staff.view" in slugs

    def test_active_assignment_grants_permission_until_revoked(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
            granted_by_id=self.revoker.id,
        )

        self.assertTrue(self._has_staff_view_at_branch(self.branch_a))

        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.revoker.id,
        )

        self.assertFalse(self._has_staff_view_at_branch(self.branch_a))

    def test_future_assignment_still_grants_permission(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
            granted_by_id=self.revoker.id,
        )
        assignment.status = AssignmentStatus.FUTURE
        assignment.save(update_fields=["status"])

        self.assertTrue(self._has_staff_view_at_branch(self.branch_a))
        permissions = rbac_bll.get_effective_permissions(
            user=self.staff_user,
            tenant=self.tenant,
        )
        self.assertIn("staff.view", permissions)

    def test_expired_assignment_does_not_grant_permission(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
            granted_by_id=self.revoker.id,
        )
        assignment.status = AssignmentStatus.EXPIRED
        assignment.save(update_fields=["status"])

        self.assertFalse(self._has_staff_view_at_branch(self.branch_a))

    def test_active_grant_survives_when_other_assignment_revoked(self):
        active = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
            granted_by_id=self.revoker.id,
        )
        revoked = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            branch_ids=[self.branch_b.id],
            granted_by_id=self.revoker.id,
        )
        assignment_bll.revoke_assignment(
            assignment_id=revoked.id,
            revoked_by_id=self.revoker.id,
        )

        self.assertTrue(self._has_staff_view_at_branch(self.branch_a))

        assignment_bll.revoke_assignment(
            assignment_id=active.id,
            revoked_by_id=self.revoker.id,
        )

        self.assertFalse(self._has_staff_view_at_branch(self.branch_a))

    def test_revoked_tenant_wide_assignment_does_not_authorize(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            all_locations=True,
            granted_by_id=self.revoker.id,
        )

        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))

        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.revoker.id,
        )

        self.assertFalse(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertFalse(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))

    def test_revoked_multi_location_assignment_does_not_authorize_any_branch(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id, self.branch_b.id],
            granted_by_id=self.revoker.id,
        )

        self.assertTrue(self._has_staff_view_at_branch(self.branch_a))
        self.assertTrue(self._has_staff_view_at_branch(self.branch_b))
        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))

        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.revoker.id,
        )

        self.assertFalse(self._has_staff_view_at_branch(self.branch_a))
        self.assertFalse(self._has_staff_view_at_branch(self.branch_b))
        self.assertFalse(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertFalse(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))
