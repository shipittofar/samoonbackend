"""Wave 1.5 integration tests — canonical writes, unified scope, eligibility."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import (
    Role,
    StaffAssignment,
    StaffMembership,
    StaffMembershipStatus,
)
from access.selectors.permission_dal import permission_selector
from access.services.assignment_bll import assignment_bll
from access.services.assignment_scope import assignment_covers_branch_q
from access.services.membership_bll import membership_service
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


class CanonicalAssignmentWriteTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = Role.objects.get(slug="manager")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(tenant=self.tenant, name="Branch A")
        self.branch_b = Branch.objects.create(tenant=self.tenant, name="Branch B")

    def test_single_branch_writes_junction_row(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_id=self.branch_a.id,
        )

        self.assertFalse(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 1)
        self.assertEqual(
            assignment.locations.get().branch_id,
            self.branch_a.id,
        )

    def test_multi_branch_writes_one_assignment_with_multiple_locations(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id, self.branch_b.id],
        )

        self.assertFalse(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 2)
        self.assertEqual(
            StaffAssignment.objects.filter(membership=self.membership).count(),
            1,
        )

    def test_tenant_wide_sets_all_locations_without_junction_rows(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_id=None,
        )

        self.assertTrue(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 0)

    def test_membership_service_delegates_to_canonical_writer(self):
        assignment = membership_service.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_id=self.branch_a.id,
        )

        self.assertEqual(assignment.locations.count(), 1)

    def test_permission_resolution_uses_junction_after_canonical_write(self):
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
        )

        slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=self.branch_a.id,
        )
        self.assertIn("staff.view", slugs)

        other_branch_slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=self.branch_b.id,
        )
        self.assertNotIn("staff.view", other_branch_slugs)

    def test_workspace_bll_uses_canonical_scope_for_multi_location_grant(self):
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id, self.branch_b.id],
        )

        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))


class IneligibleTenantAuthorizationTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.waiter_role = Role.objects.get(slug="waiter")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            branch_id=None,
        )

    def test_inactive_tenant_denies_require_permission_for_staff(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=["is_active"])

        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.put(
            f"/api/tenants/{self.tenant.id}/website/layout/",
            {"sections": []},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "tenant_access_denied")

    def test_closed_tenant_denies_require_permission_for_staff(self):
        self.tenant.status = TenantStatus.CLOSED
        self.tenant.save(update_fields=["status"])

        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.put(
            f"/api/tenants/{self.tenant.id}/website/layout/",
            {"sections": []},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "tenant_access_denied")

    def test_closed_tenant_denies_owner_via_require_permission(self):
        self.tenant.status = TenantStatus.CLOSED
        self.tenant.save(update_fields=["status"])

        client = APIClient()
        client.force_authenticate(user=self.owner_user)
        response = client.put(
            f"/api/tenants/{self.tenant.id}/website/layout/",
            {"sections": []},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "tenant_access_denied")

    def test_closed_tenant_owner_gets_no_effective_permissions(self):
        self.tenant.status = TenantStatus.CLOSED
        self.tenant.save(update_fields=["status"])

        permissions = rbac_bll.get_effective_permissions(
            user=self.owner_user,
            tenant=self.tenant,
        )
        self.assertEqual(permissions, [])


class UnifiedScopeHelperTests(TestCase):
    def test_assignment_covers_branch_q_matches_m2m_rows(self):
        _, tenant = make_tenant()
        staff_user = make_user()
        role = Role.objects.get(slug="manager")
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        branch = Branch.objects.create(tenant=tenant, name="Scoped Branch")
        assignment = assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=role.id,
            branch_ids=[branch.id],
        )

        matched = StaffAssignment.objects.filter(
            id=assignment.id,
        ).filter(assignment_covers_branch_q(branch_id=branch.id))
        self.assertTrue(matched.exists())
