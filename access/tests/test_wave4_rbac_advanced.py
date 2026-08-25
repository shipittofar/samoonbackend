"""Wave 4 — permission overrides, effective permissions API, role editing, audit, cache."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.constants import MembershipStatus
from access.models import (
    Permission,
    PermissionAudit,
    PermissionAuditAction,
    PermissionOverrideEffect,
    Role,
    RolePermission,
)
from access.services.assignment_bll import assignment_bll
from access.services.membership_bll import membership_service
from access.services.permission_override_bll import permission_override_bll
from access.services.rbac_bll import rbac_bll
from access.services.role_bll import role_service
from access.tests.helpers import (
    get_role,
    make_membership,
    make_tenant,
    make_user,
)
from accounts.models import User
from tenants.models import Owner
from tenants.services.place_bll import TenantBusinessLogicLayer


class PermissionOverrideLogicTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.waiter_role = get_role("waiter")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        self.analytics_permission = Permission.objects.get(slug="analytics.view")
        self.orders_view_permission = Permission.objects.get(slug="orders.view")

    def test_allow_override_grants_permission_not_in_role(self):
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=self.analytics_permission.id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )

        effective = rbac_bll.get_effective_permissions(
            user=self.staff_user, tenant=self.tenant
        )
        self.assertIn("analytics.view", effective)
        self.assertNotIn("analytics.view", ROLE_PERMISSIONS["waiter"])

    def test_deny_override_removes_role_permission(self):
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=self.orders_view_permission.id,
            effect=PermissionOverrideEffect.DENY,
            created_by_id=self.owner_user.id,
        )

        effective = rbac_bll.get_effective_permissions(
            user=self.staff_user, tenant=self.tenant
        )
        self.assertNotIn("orders.view", effective)
        self.assertIn("orders.view", ROLE_PERMISSIONS["waiter"])

    def test_deny_precedence_wins_over_allow_for_same_permission(self):
        allow_override = SimpleNamespace(
            effect=PermissionOverrideEffect.ALLOW,
            permission=SimpleNamespace(slug="analytics.view"),
        )
        deny_override = SimpleNamespace(
            effect=PermissionOverrideEffect.DENY,
            permission=SimpleNamespace(slug="analytics.view"),
        )

        inherited = {"orders.view"}
        effective = rbac_bll._apply_permission_overrides(
            inherited,
            [allow_override, deny_override],
        )
        self.assertNotIn("analytics.view", effective)

    def test_effective_permissions_breakdown_includes_overrides(self):
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=self.analytics_permission.id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )

        breakdown = rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=False,
        )
        self.assertIn("analytics.view", breakdown["permissions"])
        self.assertNotIn("analytics.view", breakdown["inherited_permissions"])
        self.assertEqual(
            breakdown["overrides"],
            [{"permission": "analytics.view", "effect": "allow"}],
        )


class PermissionOverrideApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.waiter_role = get_role("waiter")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        self.permission = Permission.objects.get(slug="analytics.view")
        self.base_url = (
            f"/api/authorization/tenants/{self.tenant.id}/permission-overrides/"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)

    def test_create_list_patch_delete_override(self):
        create_response = self.client.post(
            self.base_url,
            {
                "membership_id": str(self.membership.id),
                "permission_id": str(self.permission.id),
                "effect": "allow",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        override_id = create_response.data["id"]
        self.assertEqual(create_response.data["effect"], "allow")
        self.assertEqual(create_response.data["permission"]["slug"], "analytics.view")
        self.assertEqual(create_response.data["created_by"], str(self.owner_user.id))

        list_response = self.client.get(self.base_url)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data["results"]), 1)

        patch_response = self.client.patch(
            f"{self.base_url}{override_id}/",
            {"effect": "deny"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data["effect"], "deny")

        delete_response = self.client.delete(f"{self.base_url}{override_id}/")
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(
            self.client.get(self.base_url).data["results"],
            [],
        )


class MeEffectivePermissionsApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.waiter_role = get_role("waiter")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            all_locations=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff_user)

    def test_effective_permissions_endpoint_returns_breakdown(self):
        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=Permission.objects.get(slug="analytics.view").id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )

        response = self.client.get(
            "/api/auth/me/effective-permissions/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("permissions", response.data)
        self.assertIn("inherited_permissions", response.data)
        self.assertIn("overrides", response.data)
        self.assertIn("analytics.view", response.data["permissions"])
        self.assertEqual(
            response.data["overrides"],
            [{"permission": "analytics.view", "effect": "allow"}],
        )


class RolePermissionEditingTests(TestCase):
    def setUp(self):
        self.admin_user = make_user(is_staff=True, is_superuser=True)
        self.role = Role.objects.create(
            slug=f"custom-{uuid.uuid4().hex[:8]}",
            name="Custom Role",
            description="Wave 4 test role",
        )
        self.permission_a = Permission.objects.get(slug="orders.view")
        self.permission_b = Permission.objects.get(slug="menu.view")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)
        self.url = f"/api/authorization/roles/{self.role.id}/permissions/"

    def test_get_and_put_role_permissions(self):
        empty_response = self.client.get(self.url)
        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(empty_response.data, [])

        put_response = self.client.put(
            self.url,
            {
                "permission_ids": [
                    str(self.permission_a.id),
                    str(self.permission_b.id),
                ]
            },
            format="json",
        )
        self.assertEqual(put_response.status_code, 200)
        returned_slugs = {item["slug"] for item in put_response.data}
        self.assertEqual(returned_slugs, {"orders.view", "menu.view"})

        get_response = self.client.get(self.url)
        self.assertEqual(len(get_response.data), 2)

        replace_response = self.client.put(
            self.url,
            {"permission_ids": [str(self.permission_a.id)]},
            format="json",
        )
        self.assertEqual(replace_response.status_code, 200)
        self.assertEqual(len(replace_response.data), 1)
        self.assertEqual(replace_response.data[0]["slug"], "orders.view")


class PermissionAuditTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = get_role("manager")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)
        self.audit_url = (
            f"/api/authorization/tenants/{self.tenant.id}/permission-audit/"
        )

    def test_assignment_override_and_role_permission_audits(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        assignment_bll.update_assignment(
            assignment_id=assignment.id,
            mode="read",
            updated_by_id=self.owner_user.id,
        )
        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.owner_user.id,
        )

        permission = Permission.objects.get(slug="analytics.view")
        override = permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=permission.id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )
        permission_override_bll.update_override(
            tenant_id=self.tenant.id,
            override_id=override.id,
            effect=PermissionOverrideEffect.DENY,
            actor_id=self.owner_user.id,
        )
        permission_override_bll.delete_override(
            tenant_id=self.tenant.id,
            override_id=override.id,
            actor_id=self.owner_user.id,
        )

        custom_role = Role.objects.create(
            slug=f"audit-role-{uuid.uuid4().hex[:6]}",
            name="Audit Role",
        )
        role_service.replace_role_permissions(
            role_id=custom_role.id,
            permission_ids=[permission.id],
            actor_id=self.owner_user.id,
            can_manage_roles=True,
        )

        actions = set(
            PermissionAudit.objects.filter(tenant_id=self.tenant.id).values_list(
                "action", flat=True
            )
        )
        self.assertIn(PermissionAuditAction.ASSIGNMENT_CREATED, actions)
        self.assertIn(PermissionAuditAction.ASSIGNMENT_UPDATED, actions)
        self.assertIn(PermissionAuditAction.ASSIGNMENT_REVOKED, actions)
        self.assertIn(PermissionAuditAction.OVERRIDE_CREATED, actions)
        self.assertIn(PermissionAuditAction.OVERRIDE_UPDATED, actions)
        self.assertIn(PermissionAuditAction.OVERRIDE_REMOVED, actions)

        role_audit_exists = PermissionAudit.objects.filter(
            action=PermissionAuditAction.ROLE_PERMISSIONS_CHANGED,
            metadata__role_id=str(custom_role.id),
        ).exists()
        self.assertTrue(role_audit_exists)

        response = self.client.get(self.audit_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
        self.assertGreaterEqual(response.data["count"], 6)

    def test_ownership_transfer_audit(self):
        new_owner_user = make_user()
        new_owner = Owner.objects.create(user=new_owner_user)
        old_owner_id = self.tenant.owner_id

        TenantBusinessLogicLayer.update_tenant(
            tenant_id=self.tenant.id,
            actor_id=self.owner_user.id,
            owner=new_owner_user.id,
            name=self.tenant.name,
            status=self.tenant.status,
        )

        audit = PermissionAudit.objects.filter(
            tenant_id=self.tenant.id,
            action=PermissionAuditAction.OWNERSHIP_TRANSFERRED,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.metadata["old_owner"], str(old_owner_id))
        self.assertEqual(audit.metadata["new_owner"], str(new_owner.id))
        self.assertEqual(audit.actor_id, self.owner_user.id)


class CacheInvalidationTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.waiter_role = get_role("waiter")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.waiter_role.id,
            all_locations=True,
        )
        self.cache_key = rbac_bll._effective_permissions_cache_key(
            self.staff_user.id,
            self.tenant.id,
        )

    def test_override_invalidates_effective_permissions_cache(self):
        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        self.assertIsNotNone(cache.get(self.cache_key))

        permission_override_bll.create_override(
            tenant_id=self.tenant.id,
            membership_id=self.membership.id,
            permission_id=Permission.objects.get(slug="analytics.view").id,
            effect=PermissionOverrideEffect.ALLOW,
            created_by_id=self.owner_user.id,
        )
        self.assertIsNone(cache.get(self.cache_key))

    def test_assignment_update_invalidates_effective_permissions_cache(self):
        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        self.assertIsNotNone(cache.get(self.cache_key))

        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=get_role("manager").id,
            all_locations=True,
            granted_by_id=self.owner_user.id,
        )
        self.assertIsNone(cache.get(self.cache_key))

        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        self.assertIsNotNone(cache.get(self.cache_key))

        assignment_bll.revoke_assignment(
            assignment_id=assignment.id,
            revoked_by_id=self.owner_user.id,
        )
        self.assertIsNone(cache.get(self.cache_key))

    def test_role_permission_replace_invalidates_reference_and_effective_caches(self):
        from access.services.rbac_bll import (
            PERMISSIONS_CATALOG_CACHE_KEY,
            ROLES_CATALOG_CACHE_KEY,
        )

        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        cache.set(PERMISSIONS_CATALOG_CACHE_KEY, ["cached"], timeout=60)
        cache.set(ROLES_CATALOG_CACHE_KEY, ["cached"], timeout=60)
        self.assertIsNotNone(cache.get(self.cache_key))

        role_service.replace_role_permissions(
            role_id=self.waiter_role.id,
            permission_ids=list(
                Permission.objects.filter(slug="orders.view").values_list("id", flat=True)
            ),
            actor_id=self.owner_user.id,
            can_manage_roles=True,
        )

        self.assertIsNone(cache.get(self.cache_key))
        self.assertIsNone(cache.get(PERMISSIONS_CATALOG_CACHE_KEY))
        self.assertIsNone(cache.get(ROLES_CATALOG_CACHE_KEY))

    def test_membership_status_changes_invalidate_effective_permissions_cache(self):
        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        self.assertIsNotNone(cache.get(self.cache_key))

        with self.captureOnCommitCallbacks(execute=True):
            membership_service.update_membership(
                tenant_id=self.tenant.id,
                membership_id=self.membership.id,
                status=MembershipStatus.SUSPENDED,
            )
        self.assertIsNone(cache.get(self.cache_key))

        rbac_bll.get_effective_permissions_breakdown(
            user=self.staff_user,
            tenant=self.tenant,
            use_cache=True,
        )
        self.assertIsNotNone(cache.get(self.cache_key))

        with self.captureOnCommitCallbacks(execute=True):
            membership_service.remove_membership(
                tenant_id=self.tenant.id,
                membership_id=self.membership.id,
            )
        self.assertIsNone(cache.get(self.cache_key))

    def test_membership_create_invalidates_effective_permissions_cache(self):
        other_user = make_user()
        cache_key = rbac_bll._effective_permissions_cache_key(
            other_user.id,
            self.tenant.id,
        )
        # Prime an empty/stale entry that must be cleared on create.
        cache.set(cache_key, {"permissions": [], "inherited_permissions": [], "overrides": []})

        with self.captureOnCommitCallbacks(execute=True):
            membership_service.create_membership(
                tenant_id=self.tenant.id,
                user_id=other_user.id,
                status=MembershipStatus.ACTIVE,
            )
        self.assertIsNone(cache.get(cache_key))
