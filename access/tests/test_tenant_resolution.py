"""Integration tests for tenant resolution and effective permission union."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.models import Role, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
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


def make_owner_tenant(user=None, name=None):
    if user is None:
        user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(status=TenantStatus.ACTIVE, 
        owner=owner,
        name=name or f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class TenantResolutionTests(TestCase):
    def test_x_tenant_slug_takes_precedence(self):
        user, tenant_a = make_owner_tenant(name="Alpha Tenant")
        other_owner = Owner.objects.create(user=make_user())
        tenant_b = Tenant.objects.create(status=TenantStatus.ACTIVE, owner=other_owner, name="Beta Tenant")
        StaffMembership.objects.create(
            user=user,
            tenant=tenant_b,
            status=StaffMembershipStatus.ACTIVE,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant.manage", response.json()["permissions"])
        self.assertNotIn(
            "tenant.manage",
            rbac_bll.get_effective_permissions(user=user, tenant=tenant_b),
        )

    def test_x_tenant_id_fallback(self):
        user, tenant = make_owner_tenant()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_ID=str(tenant.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["permissions"]), 0)

    def test_conflicting_slug_and_id_returns_400(self):
        user, tenant_a = make_owner_tenant()
        _user_b, tenant_b = make_owner_tenant()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            "/api/auth/me/permissions/",
            HTTP_X_TENANT_SLUG=tenant_a.slug,
            HTTP_X_TENANT_ID=str(tenant_b.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"]["code"],
            "tenant_context_mismatch",
        )

    def test_single_membership_fallback(self):
        user, tenant = make_owner_tenant()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["permissions"]), 0)

    def test_zero_tenant_returns_no_tenant_context(self):
        user = make_user()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "no_tenant_context")

    def test_multi_tenant_without_context_returns_ambiguous(self):
        user, _tenant_a = make_owner_tenant()
        other_owner = Owner.objects.create(user=make_user())
        tenant_b = Tenant.objects.create(status=TenantStatus.ACTIVE, 
            owner=other_owner,
            name=f"Other {uuid.uuid4().hex[:4]}",
        )
        StaffMembership.objects.create(
            user=user,
            tenant=tenant_b,
            status=StaffMembershipStatus.ACTIVE,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/permissions/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "ambiguous_tenant")


class DualRolePermissionUnionTests(TestCase):
    def test_owner_plus_staff_unions_permissions(self):
        user, tenant = make_owner_tenant()
        manager_role = Role.objects.get(slug="manager")
        membership = StaffMembership.objects.create(
            user=user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=manager_role.id,
            all_locations=True,
        )

        effective = set(rbac_bll.get_effective_permissions(user=user, tenant=tenant))
        owner_perms = ROLE_PERMISSIONS["owner"]
        manager_perms = ROLE_PERMISSIONS["manager"]

        self.assertTrue(owner_perms.issubset(effective))
        self.assertTrue(manager_perms.issubset(effective))
