"""Security invariant: admin RBAC role is superuser-only for visibility and assignment."""
from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.services.assignment_bll import assignment_bll
from access.services.permission_audit_bll import permission_audit_bll
from access.tests.helpers import (
    create_canonical_assignment,
    get_role,
    make_branch,
    make_membership,
    make_tenant,
    make_user,
)


class AdminRoleExposureTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.admin_role = get_role("admin")
        self.manager_role = get_role("manager")
        self.staff_user = make_user()
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        self.admin_assignment = create_canonical_assignment(
            membership=self.membership,
            role=self.admin_role,
            all_locations=True,
        )
        self.superuser = make_user(is_staff=True, is_superuser=True)
        self.platform_staff = make_user(is_staff=True, is_superuser=False)
        self.client = APIClient()

    def _assignment_url(self):
        return f"/api/authorization/tenants/{self.tenant.id}/staff-assignments/"

    def test_tenant_roles_list_hides_admin_for_owner(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(f"/api/tenants/{self.tenant.id}/roles/")
        self.assertEqual(response.status_code, 200)
        slugs = {item["slug"] for item in response.data}
        self.assertNotIn("admin", slugs)

    def test_tenant_roles_list_includes_admin_for_superuser(self):
        super_owner = make_user(is_staff=True, is_superuser=True)
        from tenants.models import Owner, Tenant, TenantStatus

        owner = Owner.objects.create(user=super_owner)
        tenant = Tenant.objects.create(
            owner=owner,
            name=f"Super Tenant {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        self.client.force_authenticate(user=super_owner)
        response = self.client.get(f"/api/tenants/{tenant.id}/roles/")
        self.assertEqual(response.status_code, 200)
        slugs = {item["slug"] for item in response.data}
        self.assertIn("admin", slugs)

    def _role_items(self, response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    def test_global_role_list_hides_admin_for_platform_staff(self):
        self.client.force_authenticate(user=self.platform_staff)
        response = self.client.get("/api/authorization/roles/")
        self.assertEqual(response.status_code, 200)
        slugs = {item["slug"] for item in self._role_items(response)}
        self.assertNotIn("admin", slugs)

    def test_global_role_list_includes_admin_for_superuser(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/api/authorization/roles/")
        self.assertEqual(response.status_code, 200)
        slugs = {item["slug"] for item in self._role_items(response)}
        self.assertIn("admin", slugs)

    def test_global_role_detail_admin_returns_404_for_platform_staff(self):
        self.client.force_authenticate(user=self.platform_staff)
        response = self.client.get(
            f"/api/authorization/roles/{self.admin_role.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_global_role_detail_admin_visible_for_superuser(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get(
            f"/api/authorization/roles/{self.admin_role.id}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], "admin")

    def test_owner_cannot_assign_admin_role(self):
        other_staff = make_user()
        other_membership = make_membership(user=other_staff, tenant=self.tenant)
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.post(
            self._assignment_url(),
            {
                "membership_id": str(other_membership.id),
                "role_id": str(self.admin_role.id),
                "location_ids": [],
                "all_locations": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "admin_role_access_denied")

    def test_superuser_can_assign_admin_role(self):
        super_owner = make_user(is_staff=True, is_superuser=True)
        from tenants.models import Owner, Tenant, TenantStatus

        owner = Owner.objects.create(user=super_owner)
        tenant = Tenant.objects.create(
            owner=owner,
            name=f"Super Tenant {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        other_staff = make_user()
        other_membership = make_membership(user=other_staff, tenant=tenant)
        branch = make_branch(tenant)
        self.client.force_authenticate(user=super_owner)
        response = self.client.post(
            f"/api/authorization/tenants/{tenant.id}/staff-assignments/",
            {
                "membership_id": str(other_membership.id),
                "role_id": str(self.admin_role.id),
                "location_ids": [str(branch.id)],
                "all_locations": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"]["slug"], "admin")

    def test_staff_assignment_list_hides_admin_assignments_for_owner(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self._assignment_url())
        self.assertEqual(response.status_code, 200)
        roles = {item["role"]["slug"] for item in response.data["results"]}
        self.assertNotIn("admin", roles)

    def test_staff_assignment_detail_admin_returns_404_for_owner(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(
            f"{self._assignment_url()}{self.admin_assignment.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_me_hides_admin_role_for_staff_with_admin_assignment(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        tenant_roles = {item["role"] for item in response.data["tenantRoles"]}
        assignment_roles = {item["role"] for item in response.data["staffAssignments"]}
        membership_roles = {
            role
            for membership in response.data["memberships"]
            for role in membership["roles"]
        }
        self.assertNotIn("admin", tenant_roles)
        self.assertNotIn("admin", assignment_roles)
        self.assertNotIn("admin", membership_roles)

    def test_me_includes_admin_for_superuser_with_admin_assignment(self):
        super_staff = make_user(is_staff=True, is_superuser=True)
        membership = make_membership(user=super_staff, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=self.admin_role.id,
            all_locations=True,
            granted_by_id=self.superuser.id,
        )
        self.client.force_authenticate(user=super_staff)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        assignment_roles = {item["role"] for item in response.data["staffAssignments"]}
        self.assertIn("admin", assignment_roles)

    def test_platform_staff_cannot_create_role_with_admin_slug(self):
        self.client.force_authenticate(user=self.platform_staff)
        response = self.client.post(
            "/api/authorization/roles/",
            {"slug": "admin", "name": "Fake Admin", "description": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "admin_role_access_denied")

    def test_permission_audit_hides_admin_assignment_events_for_owner(self):
        permission_audit_bll.record_assignment_created(
            assignment=self.admin_assignment,
            actor_id=self.owner_user.id,
        )
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(
            f"/api/authorization/tenants/{self.tenant.id}/permission-audit/"
        )
        self.assertEqual(response.status_code, 200)
        for entry in response.data["results"]:
            metadata = entry.get("metadata") or {}
            self.assertNotEqual(metadata.get("role_slug"), "admin")

    def test_admin_role_permissions_endpoint_hidden_for_platform_staff(self):
        self.client.force_authenticate(user=self.platform_staff)
        response = self.client.get(
            f"/api/authorization/roles/{self.admin_role.id}/permissions/"
        )
        self.assertEqual(response.status_code, 404)

    def test_admin_role_permissions_endpoint_available_for_superuser(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get(
            f"/api/authorization/roles/{self.admin_role.id}/permissions/"
        )
        self.assertEqual(response.status_code, 200)
