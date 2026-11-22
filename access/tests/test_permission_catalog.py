"""Tests for permission catalog and tenant roles endpoints."""
import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import Role, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import PERMISSIONS_CATALOG_CACHE_KEY, ROLES_CATALOG_CACHE_KEY
from accounts.models import User
from tenants.models import Owner, Tenant, TenantStatus


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


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(status=TenantStatus.ACTIVE, 
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class PermissionCatalogTests(TestCase):
    def test_permissions_catalog_returns_key_field(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get("/api/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertGreater(len(response.data), 0)
        self.assertIn("id", response.data[0])
        self.assertIn("key", response.data[0])
        self.assertIn("resource", response.data[0])
        self.assertIn("action", response.data[0])

    def test_permissions_catalog_includes_uuid_for_settings_manage(self):
        from access.models import Permission

        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        permission = Permission.objects.get(slug="settings.manage")

        response = client.get("/api/permissions/")

        self.assertEqual(response.status_code, 200)
        entry = next(item for item in response.data if item["key"] == "settings.manage")
        self.assertEqual(str(entry["id"]), str(permission.id))
        self.assertEqual(entry["key"], "settings.manage")
        self.assertEqual(entry["resource"], "settings")
        self.assertEqual(entry["action"], "manage")
        self.assertEqual(entry["description"], permission.description)

    @patch("access.services.cache_utils.cache.get")
    def test_permissions_catalog_uses_cache(self, mock_cache_get):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        cached = [
            {
                "id": str(uuid.uuid4()),
                "key": "orders.view",
                "resource": "orders",
                "action": "view",
                "description": "x",
            }
        ]
        mock_cache_get.return_value = cached

        response = client.get("/api/permissions/")

        mock_cache_get.assert_called_with(PERMISSIONS_CATALOG_CACHE_KEY, None)
        self.assertEqual(response.data, cached)


class TenantRolesEndpointTests(TestCase):
    def test_non_member_gets_tenant_access_denied(self):
        owner_user, tenant = make_tenant_with_owner()
        outsider = make_user()

        client = APIClient()
        client.force_authenticate(user=outsider)
        response = client.get(f"/api/tenants/{tenant.id}/roles/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "tenant_access_denied")

    def test_member_without_staff_view_gets_permission_denied(self):
        owner_user, tenant = make_tenant_with_owner()
        staff_user = make_user()
        waiter_role = Role.objects.get(slug="waiter")
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=waiter_role.id,
            all_locations=True,
        )

        client = APIClient()
        client.force_authenticate(user=staff_user)
        response = client.get(f"/api/tenants/{tenant.id}/roles/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_owner_can_list_roles(self):
        owner_user, tenant = make_tenant_with_owner()

        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(f"/api/tenants/{tenant.id}/roles/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 7)
        slugs = {item["slug"] for item in response.data}
        self.assertNotIn("admin", slugs)
        self.assertIn("permissions", response.data[0])

    @patch("access.services.cache_utils.cache.get")
    def test_roles_catalog_uses_cache(self, mock_cache_get):
        owner_user, tenant = make_tenant_with_owner()
        cached = [
            {
                "id": str(uuid.uuid4()),
                "name": "Owner",
                "slug": "owner",
                "is_system_role": True,
                "editable": False,
                "permissions": [],
            }
        ]

        def cache_get_side_effect(key, default=None):
            if key == ROLES_CATALOG_CACHE_KEY:
                return cached
            return default

        mock_cache_get.side_effect = cache_get_side_effect

        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(f"/api/tenants/{tenant.id}/roles/")

        mock_cache_get.assert_any_call(ROLES_CATALOG_CACHE_KEY, None)
        self.assertEqual(response.data, cached)


class MePermissionsTests(TestCase):
    def test_ambiguous_tenant_returns_400(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        Tenant.objects.create(status=TenantStatus.ACTIVE, owner=owner, name=f"T1 {uuid.uuid4().hex[:4]}")
        other_owner = Owner.objects.create(user=make_user())
        other_tenant = Tenant.objects.create(status=TenantStatus.ACTIVE, 
            owner=other_owner,
            name=f"T2 {uuid.uuid4().hex[:4]}",
        )
        StaffMembership.objects.create(
            user=user,
            tenant=other_tenant,
            status=StaffMembershipStatus.ACTIVE,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "ambiguous_tenant")

    def test_zero_tenant_returns_no_tenant_context(self):
        user = make_user()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "no_tenant_context")
