"""Staff-scoped subject resolution for GET /auth/me/effective-permissions/."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.models import Permission, PermissionOverrideEffect, Role
from access.services.assignment_bll import assignment_bll
from access.services.permission_override_bll import permission_override_bll
from access.tests.helpers import get_role, make_membership, make_tenant, make_user


OWNER_ONLY_PERMS = frozenset(
    {"settings.manage", "tenant.manage", "staff.manage"}
)


class StaffScopedEffectivePermissionsApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.other_staff = make_user()
        self.kitchen = get_role("kitchen")
        self.support = get_role("support")
        self.waiter = get_role("waiter")

        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        self.other_membership = make_membership(
            user=self.other_staff, tenant=self.tenant
        )
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.kitchen.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.support.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )

        self.client = APIClient()
        self.url = "/api/auth/me/effective-permissions/"
        self.tenant_header = {"HTTP_X_TENANT_ID": str(self.tenant.id)}

    def _get(self, *, user, **query):
        self.client.force_authenticate(user=user)
        return self.client.get(self.url, query, **self.tenant_header)

    def test_self_without_subject_params_returns_request_user_permissions(self):
        response = self._get(user=self.owner_user)
        self.assertEqual(response.status_code, 200)
        perms = set(response.data["permissions"])
        self.assertTrue(OWNER_ONLY_PERMS.issubset(perms))
        self.assertGreaterEqual(len(perms), 50)

    def test_owner_inspects_staff_via_membership_id(self):
        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(response.status_code, 200)
        inherited = set(response.data["inherited_permissions"])
        effective = set(response.data["permissions"])
        expected = ROLE_PERMISSIONS["kitchen"] | ROLE_PERMISSIONS["support"]
        self.assertTrue(expected.issubset(inherited))
        self.assertTrue(expected.issubset(effective))
        self.assertTrue(OWNER_ONLY_PERMS.isdisjoint(effective))
        self.assertLess(len(effective), 30)

    def test_owner_inspects_staff_via_user_id(self):
        response = self._get(
            user=self.owner_user,
            user_id=str(self.staff_user.id),
        )
        self.assertEqual(response.status_code, 200)
        effective = set(response.data["permissions"])
        self.assertTrue(ROLE_PERMISSIONS["kitchen"].issubset(effective))
        self.assertTrue(OWNER_ONLY_PERMS.isdisjoint(effective))

    def test_both_matching_params_succeed(self):
        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
            user_id=str(self.staff_user.id),
        )
        self.assertEqual(response.status_code, 200)
        effective = set(response.data["permissions"])
        self.assertTrue(ROLE_PERMISSIONS["kitchen"].issubset(effective))
        self.assertTrue(OWNER_ONLY_PERMS.isdisjoint(effective))

    def test_mismatched_membership_and_user_id_rejected(self):
        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
            user_id=str(self.other_staff.id),
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("permissions", response.data)

    def test_cross_tenant_membership_id_rejected(self):
        other_owner, other_tenant = make_tenant()
        foreign_user = make_user()
        foreign_membership = make_membership(user=foreign_user, tenant=other_tenant)
        assignment_bll.create_assignment(
            membership_id=foreign_membership.id,
            role_id=self.kitchen.id,
            all_locations=True,
            granted_by_id=other_owner.id,
        )

        response = self._get(
            user=self.owner_user,
            membership_id=str(foreign_membership.id),
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("permissions", response.data)
        self.assertNotIn("inherited_permissions", response.data)

    def test_cross_tenant_user_id_rejected(self):
        other_owner, other_tenant = make_tenant()
        foreign_user = make_user()
        foreign_membership = make_membership(user=foreign_user, tenant=other_tenant)
        assignment_bll.create_assignment(
            membership_id=foreign_membership.id,
            role_id=self.kitchen.id,
            all_locations=True,
            granted_by_id=other_owner.id,
        )

        response = self._get(
            user=self.owner_user,
            user_id=str(foreign_user.id),
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("permissions", response.data)

    def test_multiple_active_roles_union(self):
        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(response.status_code, 200)
        inherited = set(response.data["inherited_permissions"])
        expected = ROLE_PERMISSIONS["kitchen"] | ROLE_PERMISSIONS["support"]
        self.assertEqual(inherited, expected)

    def test_revoked_assignment_excluded_from_inherited(self):
        waiter_assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        assignment_bll.revoke_assignment(
            assignment_id=waiter_assignment.id,
            revoked_by_id=self.owner_user.id,
        )

        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(response.status_code, 200)
        inherited = set(response.data["inherited_permissions"])
        waiter_only = ROLE_PERMISSIONS["waiter"] - (
            ROLE_PERMISSIONS["kitchen"] | ROLE_PERMISSIONS["support"]
        )
        self.assertTrue(waiter_only.isdisjoint(inherited))
        self.assertTrue(ROLE_PERMISSIONS["kitchen"].issubset(inherited))

    def test_permission_overrides_reflected_for_subject(self):
        deny_perm = Permission.objects.get(slug="orders.view")
        allow_perm = Permission.objects.get(slug="analytics.view")
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=deny_perm.id,
            effect=PermissionOverrideEffect.DENY,
            created_by_id=self.owner_user.id,
        )
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=allow_perm.id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )

        response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(response.status_code, 200)
        overrides = {
            item["permission"]: item["effect"] for item in response.data["overrides"]
        }
        self.assertEqual(overrides.get("orders.view"), "deny")
        self.assertEqual(overrides.get("analytics.view"), "allow")
        effective = set(response.data["permissions"])
        self.assertNotIn("orders.view", effective)
        self.assertIn("analytics.view", effective)

    def test_owner_role_assignment_still_rejected(self):
        owner_role = Role.objects.get(slug="owner")
        with self.assertRaises(ValidationError):
            assignment_bll.create_assignment(
                membership_id=self.membership.id,
                role_id=owner_role.id,
                all_locations=True,
                granted_by_id=self.owner_user.id,
            )

    def test_staff_without_staff_view_cannot_inspect_another(self):
        assignment_bll.create_assignment(
            membership_id=self.other_membership.id,
            role_id=self.kitchen.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        response = self._get(
            user=self.staff_user,
            membership_id=str(self.other_membership.id),
        )
        self.assertEqual(response.status_code, 403)

    def test_self_via_own_membership_id_allowed_without_staff_view(self):
        response = self._get(
            user=self.staff_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(response.status_code, 200)
        effective = set(response.data["permissions"])
        self.assertTrue(ROLE_PERMISSIONS["kitchen"].issubset(effective))
        self.assertTrue(OWNER_ONLY_PERMS.isdisjoint(effective))

    def test_inspecting_staff_does_not_poison_owner_cache(self):
        staff_response = self._get(
            user=self.owner_user,
            membership_id=str(self.membership.id),
        )
        self.assertEqual(staff_response.status_code, 200)
        self.assertTrue(
            OWNER_ONLY_PERMS.isdisjoint(set(staff_response.data["permissions"]))
        )

        owner_response = self._get(user=self.owner_user)
        self.assertEqual(owner_response.status_code, 200)
        self.assertTrue(
            OWNER_ONLY_PERMS.issubset(set(owner_response.data["permissions"]))
        )
