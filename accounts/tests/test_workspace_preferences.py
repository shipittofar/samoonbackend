"""Per-tenant branch preference and atomic workspace transitions."""
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from access.models import Role, StaffMembership
from access.services.membership_bll import membership_service
from access.tests.helpers import create_canonical_assignment
from accounts.models import User, UserTenantPreference
from accounts.services.workspace_bll import workspace_bll
from accounts.tests.test_active_branch import (
    make_branch,
    make_owner_user,
    make_tenant,
    make_user,
)


class PerTenantBranchPreferenceTests(TestCase):
    def test_switch_tenant_restores_preferred_branch(self):
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_a2 = make_branch(tenant_a, name="A2")
        branch_b1 = make_branch(tenant_b, name="B1")

        membership_service.switch_active_tenant(user, tenant_a.id)
        workspace_bll.switch_active_branch(user, branch_a2.id)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch_a2.id)

        membership_service.switch_active_tenant(user, tenant_b.id)
        workspace_bll.switch_active_branch(user, branch_b1.id)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant_b.id)
        self.assertEqual(user.active_branch_id, branch_b1.id)

        membership_service.switch_active_tenant(user, tenant_a.id)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant_a.id)
        self.assertEqual(user.active_branch_id, branch_a2.id)

        membership_service.switch_active_tenant(user, tenant_b.id)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch_b1.id)

    def test_branch_switch_updates_preference(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch_a2 = make_branch(tenant, name="A2")
        branch_a3 = make_branch(tenant, name="A3")

        membership_service.switch_active_tenant(user, tenant.id)
        workspace_bll.switch_active_branch(user, branch_a2.id)
        workspace_bll.switch_active_branch(user, branch_a3.id)

        preference = UserTenantPreference.objects.get(user=user, tenant=tenant)
        self.assertEqual(preference.preferred_branch_id, branch_a3.id)

        membership_service.switch_active_tenant(user, tenant.id)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch_a3.id)

    def test_switch_branch_with_null_active_tenant_promotes_tenant(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(branch.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant.id)
        self.assertEqual(user.active_branch_id, branch.id)

    def test_switch_branch_changes_active_tenant_when_needed(self):
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_b = make_branch(tenant_b)
        user.active_tenant = tenant_a
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(branch_b.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant_b.id)
        self.assertEqual(user.active_branch_id, branch_b.id)

    def test_deleted_preferred_branch_falls_back(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        deleted = make_branch(tenant, name="Gone")
        replacement = make_branch(tenant, name="Keep", is_default=True)

        membership_service.switch_active_tenant(user, tenant.id)
        workspace_bll.switch_active_branch(user, deleted.id)

        from tenants.selectors.tenant_dal import BranchDataAccessLayer

        branch_dal = BranchDataAccessLayer()
        deleted = branch_dal.inactive_branch(deleted)
        workspace_bll.reassign_active_branch_after_deletion(deleted)

        user.refresh_from_db()
        preference = UserTenantPreference.objects.get(user=user, tenant=tenant)
        self.assertEqual(preference.preferred_branch_id, replacement.id)
        self.assertEqual(user.active_branch_id, replacement.id)

    def test_staff_scoped_preference_and_restore(self):
        owner_user, owner = make_owner_user()
        tenant = make_tenant(owner)
        assigned = make_branch(tenant, name="Assigned")
        other = make_branch(tenant, name="Other")
        staff = make_user()

        role, _ = Role.objects.get_or_create(
            slug="waiter",
            defaults={"name": "Waiter", "system_role": True},
        )
        membership = StaffMembership.objects.create(
            user=staff, tenant=tenant, status="active"
        )
        create_canonical_assignment(membership=membership, role=role, branch=assigned)

        membership_service.switch_active_tenant(staff, tenant.id)
        workspace_bll.switch_active_branch(staff, assigned.id)
        staff.refresh_from_db()
        self.assertEqual(staff.active_branch_id, assigned.id)

        membership_service.switch_active_tenant(staff, tenant.id)
        staff.refresh_from_db()
        self.assertEqual(staff.active_branch_id, assigned.id)

        client = APIClient()
        client.force_authenticate(user=staff)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(other.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_auth_me_bootstraps_sole_tenant_workspace(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["activeMembership"]["tenantId"], str(tenant.id))
        self.assertEqual(body["activeMembership"]["branchId"], str(branch.id))
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant.id)
        self.assertEqual(user.active_branch_id, branch.id)

    def test_membership_removal_deletes_preference_and_clears_workspace(self):
        owner_user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)
        staff = make_user()
        membership = StaffMembership.objects.create(
            user=staff, tenant=tenant, status="active"
        )
        role, _ = Role.objects.get_or_create(
            slug="waiter",
            defaults={"name": "Waiter", "system_role": True},
        )
        create_canonical_assignment(membership=membership, role=role, branch=branch)

        membership_service.switch_active_tenant(staff, tenant.id)
        workspace_bll.switch_active_branch(staff, branch.id)
        self.assertTrue(
            UserTenantPreference.objects.filter(user=staff, tenant=tenant).exists()
        )

        membership_service.remove_membership(
            tenant_id=tenant.id, membership_id=membership.id
        )
        staff.refresh_from_db()
        self.assertIsNone(staff.active_tenant_id)
        self.assertIsNone(staff.active_branch_id)
        self.assertFalse(
            UserTenantPreference.objects.filter(user=staff, tenant=tenant).exists()
        )
