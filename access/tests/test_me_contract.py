"""Tests for GET /api/auth/me contract fields."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import Role, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from accounts.models import User
from tenants.models import Owner, Tenant


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
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class MeContractTests(TestCase):
    def test_me_includes_rbac_fields(self):
        owner_user, tenant = make_tenant_with_owner()
        client = APIClient()
        client.force_authenticate(user=owner_user)

        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("user", response.data)
        self.assertIn("memberships", response.data)
        self.assertIn("activeMembership", response.data)
        self.assertIn("tenantRoles", response.data)
        self.assertIn("ownership", response.data)
        self.assertIn("staffAssignments", response.data)

    def test_ownership_null_fields_not_fabricated(self):
        owner_user, _tenant = make_tenant_with_owner()
        client = APIClient()
        client.force_authenticate(user=owner_user)

        response = client.get("/api/auth/me/")
        ownership = response.data["ownership"][0]

        self.assertIsNone(ownership["status"])
        self.assertIsNone(ownership["plan"])
        self.assertIsNone(ownership["maxTenants"])
        self.assertIsNone(ownership["billing"]["customerId"])
        self.assertIsNone(ownership["billing"]["billingEmail"])

    def test_staff_assignment_exposes_schema_defaults(self):
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
        response = client.get("/api/auth/me/")

        assignment = response.data["staffAssignments"][0]
        self.assertEqual(assignment["mode"], "manage")
        self.assertEqual(assignment["status"], "active")
        self.assertIsNone(assignment["grantedBy"])
        self.assertEqual(assignment["branchIds"], "all")


class MeIdentityFlagTests(TestCase):
    def test_me_returns_is_superuser_and_is_verified(self):
        user = make_user(is_superuser=True, is_verified=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["user"]["is_superuser"])
        self.assertTrue(response.data["user"]["is_verified"])

    def test_me_returns_false_flags_for_tenant_owner(self):
        owner_user, _tenant = make_tenant_with_owner()
        client = APIClient()
        client.force_authenticate(user=owner_user)

        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["user"]["is_superuser"])
        self.assertIn("is_verified", response.data["user"])

    def test_password_login_then_me_preserves_identity_flags(self):
        user = make_user(
            is_superuser=True,
            is_verified=True,
            is_staff=True,
        )
        client = APIClient()
        login = client.post(
            "/api/auth/password-login/",
            {"email": user.email, "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["user"]["is_superuser"])
        self.assertTrue(response.data["user"]["is_verified"])

    def test_staff_without_superuser_login_does_not_set_is_superuser(self):
        user = make_user(is_staff=True, is_superuser=False, is_verified=True)
        client = APIClient()
        login = client.post(
            "/api/auth/password-login/",
            {"email": user.email, "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = client.get("/api/auth/me/")
        self.assertFalse(response.data["user"]["is_superuser"])
        self.assertTrue(response.data["user"]["is_verified"])
