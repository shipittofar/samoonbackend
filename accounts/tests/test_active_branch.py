"""Tests for active_branch workspace behavior."""
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from access.models import Role, StaffMembership
from access.tests.helpers import create_canonical_assignment
from accounts.models import User
from accounts.services.workspace_bll import workspace_bll
from tenants.models import Branch, Owner, Tenant, TenantStatus
from tenants.services import BranchBusinessLogicLayer


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


def make_owner_user():
    user = make_user()
    owner = Owner.objects.create(user=user)
    return user, owner


def make_tenant(owner, **kwargs):
    # Active, like a real tenant with branches (a new INACTIVE tenant grants no RBAC).
    defaults = {"name": f"Tenant {uuid.uuid4().hex[:6]}", "status": TenantStatus.ACTIVE, "is_active": True}
    defaults.update(kwargs)
    return Tenant.objects.create(owner=owner, **defaults)


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class ActiveBranchWorkspaceTests(TestCase):
    def setUp(self):
        self.user, self.owner = make_owner_user()
        self.tenant = make_tenant(self.owner)
        self.user.active_tenant = self.tenant
        self.user.save(update_fields=["active_tenant_id"])

    def test_first_branch_auto_assigns_active_branch(self):
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=self.tenant.id,
            name="First Branch",
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_branch_id, branch.id)

    def test_first_branch_auto_assigns_all_users_on_tenant_with_null_branch(self):
        other_user, _ = make_owner_user()
        other_user.active_tenant = self.tenant
        other_user.save(update_fields=["active_tenant_id"])

        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=self.tenant.id,
            name="First Branch",
        )

        self.user.refresh_from_db()
        other_user.refresh_from_db()
        self.assertEqual(self.user.active_branch_id, branch.id)
        self.assertEqual(other_user.active_branch_id, branch.id)

    def test_second_branch_does_not_overwrite_active_branch(self):
        first = make_branch(self.tenant, name="First")
        self.user.active_branch = first
        self.user.save(update_fields=["active_branch_id"])

        second = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=self.tenant.id,
            name="Second Branch",
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_branch_id, first.id)
        self.assertNotEqual(self.user.active_branch_id, second.id)

    def test_switch_active_branch(self):
        branch_a = make_branch(self.tenant, name="A")
        branch_b = make_branch(self.tenant, name="B")

        workspace_bll.switch_active_branch(self.user, branch_b.id)

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_branch_id, branch_b.id)

    def test_delete_active_branch_repoints_to_sibling(self):
        branch_a = make_branch(self.tenant, name="A", is_default=True)
        branch_b = make_branch(self.tenant, name="B")
        self.user.active_branch = branch_b
        self.user.save(update_fields=["active_branch_id"])

        BranchBusinessLogicLayer.delete_console_branch(self.user, branch_b.id)

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_branch_id, branch_a.id)

    def test_delete_last_branch_clears_active_branch(self):
        branch = make_branch(self.tenant, name="Only")
        self.user.active_branch = branch
        self.user.save(update_fields=["active_branch_id"])

        BranchBusinessLogicLayer.delete_console_branch(self.user, branch.id)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.active_branch_id)

    def test_switch_tenant_clears_mismatched_active_branch(self):
        tenant_b = make_tenant(self.owner)
        branch_a = make_branch(self.tenant, name="A")
        self.user.active_branch = branch_a
        self.user.save(update_fields=["active_branch_id"])

        from access.services.membership_bll import membership_service

        membership_service.switch_active_tenant(self.user, str(tenant_b.id))

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_tenant_id, tenant_b.id)
        self.assertIsNone(self.user.active_branch_id)


class AuthMeActiveBranchTests(TestCase):
    def test_me_includes_branch_id_in_active_membership(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)
        user.active_tenant = tenant
        user.active_branch = branch
        user.save(update_fields=["active_tenant_id", "active_branch_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["activeMembership"],
            {"tenantId": str(tenant.id), "branchId": str(branch.id)},
        )

    def test_me_active_membership_branch_id_null_when_unset(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(
            response.json()["activeMembership"],
            {"tenantId": str(tenant.id), "branchId": None},
        )


class SwitchActiveBranchAPITests(TestCase):
    def test_switch_active_branch_endpoint(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)
        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(branch.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch.id)

    def test_switch_active_branch_rejects_wrong_tenant(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        other_owner_user, other_owner = make_owner_user()
        other_tenant = make_tenant(other_owner)
        other_branch = make_branch(other_tenant)
        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(other_branch.id)},
            format="json",
        )

        # Another owner's branch: the user is not a member of that tenant.
        self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertIsNone(user.active_branch_id)

    def test_staff_selected_scope_can_only_switch_assigned_branch(self):
        user = make_user()
        owner_user, owner = make_owner_user()
        tenant = make_tenant(owner)
        assigned = make_branch(tenant, name="Assigned")
        other = make_branch(tenant, name="Other")

        role, _ = Role.objects.get_or_create(
            slug="waiter",
            defaults={"name": "Waiter", "system_role": True},
        )
        membership = StaffMembership.objects.create(
            user=user, tenant=tenant, status="active"
        )
        create_canonical_assignment(membership=membership, role=role, branch=assigned)

        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)

        ok = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(assigned.id)},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_204_NO_CONTENT)

        denied = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(other.id)},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
