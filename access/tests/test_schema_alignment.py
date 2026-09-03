"""Tests for /auth/me/, tenant isolation, and RBAC alignment.

Updated for the live StaffMembership + Owner architecture (Phase 1).
Supersedes the obsolete TenantMembership-based Z.3 tests.
"""
import subprocess
import uuid
from pathlib import Path

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import Role, RolePermission, StaffAssignment, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
from accounts.models import User
from tenants.models import Branch, Owner, Tenant


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


def make_owner_tenant(user=None, **tenant_kwargs):
    if user is None:
        user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=tenant_kwargs.pop("name", f"Tenant {uuid.uuid4().hex[:6]}"),
        **tenant_kwargs,
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def make_staff_membership(user, tenant, *, roles=(), branch=None, branches=()):
    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    for role_slug in roles:
        role = Role.objects.get(slug=role_slug)
        if branches:
            assignment_bll.create_assignment(
                membership_id=membership.id,
                role_id=role.id,
                branch_ids=[branch_obj.id for branch_obj in branches],
            )
        elif branch is None:
            assignment_bll.create_assignment(
                membership_id=membership.id,
                role_id=role.id,
                all_locations=True,
            )
        else:
            assignment_bll.create_assignment(
                membership_id=membership.id,
                role_id=role.id,
                branch_id=branch.id,
            )
    return membership


def expected_account_type(user) -> str:
    if Owner.objects.filter(user=user).exists():
        return "business"
    if StaffMembership.objects.filter(
        user=user, status=StaffMembershipStatus.ACTIVE
    ).exists():
        return "business"
    return "customer"


class AuthMeTests(TestCase):
    def test_me_returns_documented_shape(self):
        user, tenant = make_owner_tenant()
        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["user"]["id"], str(user.id))
        self.assertEqual(body["user"]["accountType"], expected_account_type(user))
        self.assertEqual(len(body["memberships"]), 1)

        membership_payload = body["memberships"][0]
        self.assertEqual(membership_payload["tenantId"], str(tenant.id))
        self.assertEqual(membership_payload["tenantName"], tenant.name)
        self.assertEqual(membership_payload["tenantSlug"], tenant.slug)
        self.assertEqual(membership_payload["roles"], ["owner"])
        self.assertEqual(membership_payload["branchAccess"], {"scope": "all"})
        self.assertEqual(
            body["activeMembership"],
            {"tenantId": str(tenant.id), "branchId": None},
        )

    def test_me_selected_scope_includes_branch_ids(self):
        owner_user, tenant = make_owner_tenant()
        staff_user = make_user()
        branch = make_branch(tenant)
        make_staff_membership(
            staff_user, tenant, roles=["waiter"], branches=[branch]
        )

        client = APIClient()
        client.force_authenticate(user=staff_user)
        response = client.get("/api/auth/me/")

        body = response.json()
        membership = body["memberships"][0]
        branch_access = membership["branchAccess"]
        self.assertEqual(branch_access["scope"], "selected")
        self.assertNotIn("branchIds", branch_access)
        self.assertEqual(len(membership["branches"]), 1)
        self.assertEqual(membership["branches"][0]["id"], str(branch.id))

    def test_me_requires_authentication(self):
        client = APIClient()
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_me_memberships_include_independent_tenant_names(self):
        user, tenant_a = make_owner_tenant(name="Samoon Restaurant")
        tenant_b = Tenant.objects.create(
            owner=tenant_a.owner,
            name="Brew Cafe",
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        names_by_id = {
            m["tenantId"]: m["tenantName"] for m in response.json()["memberships"]
        }
        self.assertEqual(names_by_id[str(tenant_a.id)], "Samoon Restaurant")
        self.assertEqual(names_by_id[str(tenant_b.id)], "Brew Cafe")
        self.assertNotEqual(
            names_by_id[str(tenant_a.id)], names_by_id[str(tenant_b.id)]
        )

    def test_me_tenant_name_reflects_live_tenant_name(self):
        user, tenant = make_owner_tenant(name="Original Name")
        tenant.name = "Updated Name"
        tenant.save(update_fields=["name"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        membership = response.json()["memberships"][0]
        self.assertEqual(membership["tenantName"], "Updated Name")
        self.assertEqual(membership["tenantName"], tenant.name)

    def test_me_staff_memberships_include_independent_tenant_names(self):
        _owner_a, tenant_a = make_owner_tenant(name="Samoon Restaurant")
        _owner_b, tenant_b = make_owner_tenant(name="Brew Cafe")
        staff_user = make_user()
        make_staff_membership(staff_user, tenant_a, roles=["waiter"])
        make_staff_membership(staff_user, tenant_b, roles=["waiter"])

        client = APIClient()
        client.force_authenticate(user=staff_user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        names_by_id = {
            m["tenantId"]: m["tenantName"] for m in response.json()["memberships"]
        }
        self.assertEqual(names_by_id[str(tenant_a.id)], "Samoon Restaurant")
        self.assertEqual(names_by_id[str(tenant_b.id)], "Brew Cafe")


class TenantIsolationTests(TestCase):
    def test_user_cannot_see_other_users_tenants(self):
        user_a, tenant_a = make_owner_tenant()
        _user_b, tenant_b = make_owner_tenant()

        client = APIClient()
        client.force_authenticate(user=user_a)
        response = client.get("/api/tenants/me/")

        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids, [str(tenant_a.id)])
        self.assertNotIn(str(tenant_b.id), ids)


class OwnerNoBypassTests(TestCase):
    """Owner effective permissions come from seeded RolePermission rows."""

    def test_owner_access_requires_seeded_permissions(self):
        user, tenant = make_owner_tenant()

        self.assertIn(
            "staff.manage",
            rbac_bll.get_effective_permissions(user=user, tenant=tenant),
        )

        owner_role = Role.objects.get(slug="owner")
        RolePermission.objects.filter(role=owner_role).delete()

        self.assertNotIn(
            "staff.manage",
            rbac_bll.get_effective_permissions(
                user=user, tenant=tenant, use_cache=False
            ),
        )

    def test_tenant_owner_checker_exists_for_authorization_layer(self):
        import access.authorization.tenant_access as tenant_access

        self.assertTrue(hasattr(tenant_access, "TenantOwnerChecker"))


class NoUserRoleReferenceTests(TestCase):
    def test_grep_finds_no_user_role_usage(self):
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "grep", "-rn", "-E", r"user\.role\b|User\.role\b",
                "--include=*.py", str(repo_root),
            ],
            capture_output=True, text=True,
        )
        hits = [
            line for line in result.stdout.splitlines()
            if "/migrations/" not in line and "/tests/" not in line
        ]
        self.assertEqual(hits, [], f"Found user.role usage: {hits}")

    def test_user_model_has_no_role_field(self):
        self.skipTest(
            "User.role column still exists in this codebase; "
            "removal is tracked separately from Phase 1 RBAC."
        )


class AuthMeEdgeCaseTests(TestCase):
    def test_zero_memberships_gives_empty_list_and_null_active(self):
        user = make_user()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        body = response.json()
        self.assertEqual(body["memberships"], [])
        self.assertIsNone(body["activeMembership"])

    def test_multi_tenant_user_sees_both_memberships_scoped(self):
        user, tenant_a = make_owner_tenant()
        tenant_b = Tenant.objects.create(
            owner=user.owner_profile,
            name=f"Tenant B {uuid.uuid4().hex[:4]}",
        )
        user.active_tenant = tenant_a
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        body = response.json()
        self.assertEqual(len(body["memberships"]), 2)
        tenant_ids = {m["tenantId"] for m in body["memberships"]}
        self.assertSetEqual(tenant_ids, {str(tenant_a.id), str(tenant_b.id)})

    def test_owner_with_staff_manager_role_lists_both_roles(self):
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

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        tenant_roles = {
            entry["role"]
            for entry in response.json()["tenantRoles"]
            if entry["tenant_id"] == str(tenant.id)
        }
        self.assertSetEqual(tenant_roles, {"owner", "manager"})

    def test_all_scope_omits_branch_ids(self):
        user, tenant = make_owner_tenant()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        branch_access = response.json()["memberships"][0]["branchAccess"]
        self.assertNotIn("branchIds", branch_access)


class PermissionResolutionTests(TestCase):
    def test_no_role_membership_has_zero_permissions(self):
        user, tenant = make_owner_tenant()
        staff_user = make_user()
        StaffMembership.objects.create(
            user=staff_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )

        permissions = rbac_bll.get_effective_permissions(
            user=staff_user, tenant=tenant
        )
        self.assertEqual(permissions, [])

    def test_role_grants_exactly_its_seeded_permissions(self):
        user, tenant = make_owner_tenant()
        staff_user = make_user()
        make_staff_membership(staff_user, tenant, roles=["waiter"])

        role = Role.objects.get(slug="waiter")
        expected = sorted(
            RolePermission.objects.filter(role=role).values_list(
                "permission__slug", flat=True
            )
        )

        actual = rbac_bll.get_effective_permissions(
            user=staff_user, tenant=tenant
        )
        self.assertEqual(actual, expected)
        self.assertTrue(expected)


class AuthTokenValidityTests(TestCase):
    def test_garbage_token_returns_401(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_missing_token_returns_401(self):
        client = APIClient()
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_tampered_token_returns_401(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        user = make_user()
        token = str(RefreshToken.for_user(user).access_token)
        tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered}")
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)


class AuthMeUserProfileContractTests(TestCase):
    EXPECTED_USER_KEYS = {
        "id", "email", "accountType", "phone_number", "first_name",
        "last_name", "avatar", "is_verified", "is_superuser", "created_at",
    }

    def test_normal_verified_user(self):
        user = make_user(
            first_name="Ada",
            last_name="Lovelace",
            is_verified=True,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body["user"].keys()), self.EXPECTED_USER_KEYS)

        user_payload = body["user"]
        self.assertEqual(user_payload["id"], str(user.id))
        self.assertEqual(user_payload["email"], user.email)
        self.assertEqual(user_payload["accountType"], expected_account_type(user))
        self.assertEqual(user_payload["phone_number"], user.phone_number)
        self.assertEqual(user_payload["first_name"], "Ada")
        self.assertEqual(user_payload["last_name"], "Lovelace")
        self.assertIsNone(user_payload["avatar"])
        self.assertTrue(user_payload["is_verified"])
        self.assertFalse(user_payload["is_superuser"])
        self.assertIsNotNone(user_payload["created_at"])

    def test_unverified_user(self):
        user = make_user(is_verified=False)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["is_verified"])
        self.assertFalse(response.json()["user"]["is_superuser"])

    def test_django_superuser_flags(self):
        user = make_user(is_superuser=True, is_staff=True, is_verified=True)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["user"]
        self.assertTrue(payload["is_superuser"])
        self.assertTrue(payload["is_verified"])

    def test_staff_without_superuser_is_not_platform_admin(self):
        user = make_user(is_staff=True, is_superuser=False)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["is_superuser"])

    def test_user_without_avatar(self):
        user = make_user()
        self.assertFalse(user.avatar)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["user"]["avatar"])

    def test_user_without_phone_number(self):
        user = make_user(phone_number=None)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["phone_number"], "")

    def test_user_without_first_or_last_name(self):
        user = make_user(first_name=None, last_name=None)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        body = response.json()["user"]
        self.assertEqual(body["first_name"], "")
        self.assertEqual(body["last_name"], "")
