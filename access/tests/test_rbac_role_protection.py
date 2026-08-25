"""Role template protection, membership overrides, and permission resolver tests."""
from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import (
    Permission,
    PermissionOverrideEffect,
    Role,
)
from access.services.assignment_bll import assignment_bll
from access.services.permission_override_bll import permission_override_bll
from access.services.rbac_bll import rbac_bll
from access.services.role_bll import role_service
from access.tests.helpers import (
    get_role,
    make_membership,
    make_tenant,
    make_user,
)
from core.exceptions import SystemRoleModifyNotAllowedException


class RoleProtectionTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.manager_role = get_role("manager")
        self.superuser = make_user(is_staff=True, is_superuser=True)
        self.client = APIClient()

    def test_tenant_admin_cannot_create_global_role(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.post(
            "/api/authorization/roles/",
            {"slug": "custom", "name": "Custom", "description": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_tenant_admin_cannot_modify_system_role_permissions(self):
        self.client.force_authenticate(user=self.owner_user)
        permission_id = Permission.objects.first().id
        response = self.client.put(
            f"/api/authorization/roles/{self.manager_role.id}/permissions/",
            {"permission_ids": [str(permission_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_create_and_edit_custom_role(self):
        self.client.force_authenticate(user=self.superuser)
        slug = f"custom-{uuid.uuid4().hex[:6]}"
        create_response = self.client.post(
            "/api/authorization/roles/",
            {
                "slug": slug,
                "name": "Custom Role",
                "description": "Tenant-specific template",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        role_id = create_response.data["id"]
        self.assertFalse(create_response.data["system_role"])

        permission = Permission.objects.get(slug="orders.view")
        put_response = self.client.put(
            f"/api/authorization/roles/{role_id}/permissions/",
            {"permission_ids": [str(permission.id)]},
            format="json",
        )
        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(len(put_response.data), 1)

        delete_response = self.client.delete(f"/api/authorization/roles/{role_id}/")
        self.assertEqual(delete_response.status_code, 204)

    def test_system_role_cannot_be_deleted_even_by_superuser(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.delete(
            f"/api/authorization/roles/{self.manager_role.id}/"
        )
        self.assertEqual(response.status_code, 400)

    def test_role_bll_blocks_system_role_permission_replace_without_privilege(self):
        with self.assertRaises(SystemRoleModifyNotAllowedException):
            role_service.replace_role_permissions(
                role_id=self.manager_role.id,
                permission_ids=[],
                can_manage_roles=False,
            )


class TenantRolesMetadataTests(TestCase):
    def test_tenant_roles_include_protection_metadata(self):
        owner_user, tenant = make_tenant()
        client = APIClient()
        client.force_authenticate(user=owner_user)

        response = client.get(f"/api/tenants/{tenant.id}/roles/")
        self.assertEqual(response.status_code, 200)
        manager = next(item for item in response.data if item["slug"] == "manager")
        self.assertTrue(manager["is_system_role"])
        self.assertFalse(manager["editable"])
        self.assertIn("permissions", manager)


class MembershipOverrideApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_a = make_user()
        self.staff_b = make_user()
        self.manager_role = get_role("manager")
        self.membership_a = make_membership(user=self.staff_a, tenant=self.tenant)
        self.membership_b = make_membership(user=self.staff_b, tenant=self.tenant)
        for membership in (self.membership_a, self.membership_b):
            assignment_bll.create_assignment(
                membership_id=membership.id,
                role_id=self.manager_role.id,
                all_locations=True,
            )
        self.orders_view_permission = Permission.objects.get(slug="orders.view")
        self.base_url = (
            f"/api/authorization/tenants/{self.tenant.id}/memberships/"
            f"{self.membership_b.id}/permission-overrides/"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)

    def test_membership_scoped_override_crud(self):
        response = self.client.post(
            self.base_url,
            {
                "permission_id": str(self.orders_view_permission.id),
                "effect": "deny",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        override_id = response.data["id"]

        list_response = self.client.get(self.base_url)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data["results"]), 1)

        patch_response = self.client.patch(
            f"{self.base_url}{override_id}/",
            {"effect": "allow"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)

        delete_response = self.client.delete(f"{self.base_url}{override_id}/")
        self.assertEqual(delete_response.status_code, 204)


class TwoUsersSameRoleDifferentOverridesTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_a = make_user()
        self.staff_b = make_user()
        self.manager_role = get_role("manager")
        self.membership_a = make_membership(user=self.staff_a, tenant=self.tenant)
        self.membership_b = make_membership(user=self.staff_b, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=self.membership_a.id,
            role_id=self.manager_role.id,
            all_locations=True,
        )
        assignment_bll.create_assignment(
            membership_id=self.membership_b.id,
            role_id=self.manager_role.id,
            all_locations=True,
        )
        self.orders_view_permission = Permission.objects.get(slug="orders.view")

    def test_deny_override_only_affects_target_user(self):
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership_b.id,
            permission_id=self.orders_view_permission.id,
            effect=PermissionOverrideEffect.DENY,
            created_by_id=self.owner_user.id,
        )

        perms_a = rbac_bll.get_effective_permissions(
            user=self.staff_a, tenant=self.tenant, use_cache=False
        )
        perms_b = rbac_bll.get_effective_permissions(
            user=self.staff_b, tenant=self.tenant, use_cache=False
        )

        self.assertIn("orders.view", perms_a)
        self.assertNotIn("orders.view", perms_b)

    def test_assignment_revoke_removes_role_permissions(self):
        staff = make_user()
        membership = make_membership(user=staff, tenant=self.tenant)
        waiter_role = get_role("waiter")
        assignment = assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=waiter_role.id,
            all_locations=True,
        )
        waiter_perms = rbac_bll.get_effective_permissions(
            user=staff, tenant=self.tenant, use_cache=False
        )
        self.assertIn("orders.view", waiter_perms)

        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.owner_user.id,
        )
        after_revoke = rbac_bll.get_effective_permissions(
            user=staff, tenant=self.tenant, use_cache=False
        )
        self.assertEqual(after_revoke, [])

    def test_user_receives_manager_role_permissions(self):
        perms = rbac_bll.get_effective_permissions(
            user=self.staff_a, tenant=self.tenant, use_cache=False
        )
        self.assertIn("staff.view", perms)
        self.assertIn("staff.manage", perms)
        self.assertIn("orders.view", perms)

    def test_allow_override_adds_permission_not_in_role(self):
        orders_delete = Permission.objects.get(slug="orders.delete")
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership_a.id,
            permission_id=orders_delete.id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )
        perms = rbac_bll.get_effective_permissions(
            user=self.staff_a, tenant=self.tenant, use_cache=False
        )
        self.assertIn("orders.delete", perms)
