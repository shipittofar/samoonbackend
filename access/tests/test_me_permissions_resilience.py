"""Resilience tests for GET /api/auth/me/permissions/."""
import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import Role, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
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


class MePermissionsResilienceTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.client = APIClient()

    def test_unauthenticated_returns_401(self):
        response = self.client.get("/api/auth/me/permissions/")
        self.assertEqual(response.status_code, 401)

    def test_owner_returns_permissions(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)
        self.assertIsInstance(response.data["permissions"], list)
        self.assertGreater(len(response.data["permissions"]), 0)

    def test_owner_with_tenant_slug_header_returns_permissions(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
            HTTP_ORIGIN="http://localhost:3000",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)
        self.assertGreater(len(response.data["permissions"]), 0)

    def test_missing_tenant_header_resolves_single_tenant_membership(self):
        """Owner with one tenant does not require X-Tenant-Slug."""
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)

    def test_unknown_tenant_slug_returns_404(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_SLUG="does-not-exist",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "tenant_not_found")

    def test_non_member_returns_403(self):
        outsider = make_user()
        self.client.force_authenticate(user=outsider)
        response = self.client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "tenant_access_denied")

    def test_staff_without_permissions_returns_empty_list(self):
        staff_user = make_user()
        waiter_role = Role.objects.get(slug="waiter")
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=waiter_role.id,
            all_locations=True,
        )

        self.client.force_authenticate(user=staff_user)
        response = self.client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)
        self.assertIsInstance(response.data["permissions"], list)

    @patch("access.services.cache_utils.cache.get", side_effect=ConnectionError("redis down"))
    def test_cache_get_failure_still_returns_200(self, _mock_get):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)

    @patch("access.services.cache_utils.cache.set", side_effect=ConnectionError("redis down"))
    def test_cache_set_failure_still_returns_200(self, _mock_set):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)

    @patch("access.services.cache_utils.cache.delete", side_effect=ConnectionError("redis down"))
    def test_cache_delete_failure_does_not_break_permission_reads(self, _mock_delete):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)

    @patch(
        "access.services.rbac_bll.safe_cache_get",
        return_value={"permissions": "invalid", "inherited_permissions": [], "overrides": []},
    )
    def test_invalid_cached_payload_is_ignored(self, _mock_get):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data["permissions"], list)
