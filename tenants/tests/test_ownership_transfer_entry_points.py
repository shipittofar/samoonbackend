"""
Ownership-transfer entry-point matrix.

Supported production paths that may change Tenant.owner_id:
  - place_bll.transfer_ownership (canonical)
  - place_bll.update_tenant (delegates to transfer_ownership)
  - Django Admin TenantAdmin.save_model (delegates to transfer_ownership)

Confirmed NON-paths:
  - GET/POST /api/tenants/{id}/transfer-ownership/ → not wired (404)
  - Console PATCH/PUT /api/tenants/{id}/update/ → tenant_bll; does not mutate owner
"""
from __future__ import annotations

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from access.models import PermissionAudit, PermissionAuditAction
from accounts.tests.test_active_branch import make_branch, make_owner_user, make_tenant
from tenants.admin.tenant import TenantAdmin
from tenants.models import Branch, Tenant
from tenants.services.place_bll import TenantBusinessLogicLayer as PlaceTenantBLL
from tenants.services.tenant_bll import TenantBusinessLogicLayer as ConsoleTenantBLL


class OwnershipTransferEntryPointTests(TestCase):
    def _seed_transfer_fixture(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        tenant = make_tenant(old_owner, name="EntryPointTenant")
        branch = make_branch(tenant)
        old_user.active_tenant = tenant
        old_user.active_branch = branch
        old_user.save(update_fields=["active_tenant_id", "active_branch_id"])
        return old_user, old_owner, new_user, new_owner, tenant, branch

    def _assert_hardened_transfer_effects(
        self, *, old_user, new_owner, tenant, branch
    ):
        tenant.refresh_from_db()
        branch.refresh_from_db()
        old_user.refresh_from_db()

        self.assertEqual(tenant.owner_id, new_owner.id)
        self.assertEqual(branch.tenant_id, tenant.id)
        self.assertIsNone(old_user.active_tenant_id)
        self.assertIsNone(old_user.active_branch_id)
        self.assertTrue(
            PermissionAudit.objects.filter(
                tenant_id=tenant.id,
                action=PermissionAuditAction.OWNERSHIP_TRANSFERRED,
            ).exists()
        )

    def test_console_transfer_ownership_url_is_not_wired(self):
        old_user, _, _, _, tenant, _ = self._seed_transfer_fixture()
        client = APIClient()
        client.force_authenticate(user=old_user)

        response = client.post(
            f"/api/tenants/{tenant.id}/transfer-ownership/",
            {"newOwnerId": "unused"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_console_tenant_update_does_not_change_owner(self):
        old_user, old_owner, new_user, _, tenant, branch = self._seed_transfer_fixture()

        ConsoleTenantBLL.update_tenant(
            user=old_user,
            tenant_id=tenant.id,
            name="Renamed Only",
            status=tenant.status,
        )

        tenant.refresh_from_db()
        branch.refresh_from_db()
        old_user.refresh_from_db()
        self.assertEqual(tenant.owner_id, old_owner.id)
        self.assertEqual(tenant.name, "Renamed Only")
        self.assertEqual(branch.tenant_id, tenant.id)
        self.assertEqual(old_user.active_tenant_id, tenant.id)
        self.assertFalse(
            PermissionAudit.objects.filter(
                tenant_id=tenant.id,
                action=PermissionAuditAction.OWNERSHIP_TRANSFERRED,
            ).exists()
        )
        # new_user was never granted ownership via this path
        self.assertNotEqual(tenant.owner.user_id, new_user.id)

    def test_canonical_transfer_ownership_entry_point(self):
        old_user, _, new_user, new_owner, tenant, branch = self._seed_transfer_fixture()

        PlaceTenantBLL.transfer_ownership(
            tenant_id=tenant.id,
            new_owner_user_id=new_user.id,
            actor_id=old_user.id,
        )
        self._assert_hardened_transfer_effects(
            old_user=old_user,
            new_owner=new_owner,
            tenant=tenant,
            branch=branch,
        )

    def test_place_update_tenant_delegates_to_canonical_transfer(self):
        old_user, _, new_user, new_owner, tenant, branch = self._seed_transfer_fixture()

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )
        self._assert_hardened_transfer_effects(
            old_user=old_user,
            new_owner=new_owner,
            tenant=tenant,
            branch=branch,
        )

    def test_django_admin_owner_change_uses_canonical_transfer(self):
        old_user, _, new_user, new_owner, tenant, branch = self._seed_transfer_fixture()

        admin = TenantAdmin(Tenant, AdminSite())
        request = RequestFactory().post("/admin/tenants/tenant/")
        request.user = old_user

        tenant.owner = new_owner
        form = type("F", (), {"changed_data": ["owner"]})()
        admin.save_model(request, tenant, form, change=True)

        self._assert_hardened_transfer_effects(
            old_user=old_user,
            new_owner=new_owner,
            tenant=tenant,
            branch=branch,
        )

    def test_all_supported_entry_points_leave_branch_tenant_unchanged(self):
        """Matrix regression: Branch.tenant_id never moves on transfer."""
        paths = []

        for label, runner in (
            ("transfer_ownership", lambda o, n, t: PlaceTenantBLL.transfer_ownership(
                tenant_id=t.id, new_owner_user_id=n.id, actor_id=o.id
            )),
            ("update_tenant", lambda o, n, t: PlaceTenantBLL.update_tenant(
                tenant_id=t.id,
                actor_id=o.id,
                owner=n.id,
                name=t.name,
                status=t.status,
            )),
        ):
            old_user, _, new_user, _, tenant, branch = self._seed_transfer_fixture()
            branch_id = branch.id
            tenant_id = tenant.id
            runner(old_user, new_user, tenant)
            branch.refresh_from_db()
            self.assertEqual(branch.tenant_id, tenant_id, msg=label)
            self.assertEqual(branch.id, branch_id, msg=label)
            paths.append(label)

        self.assertEqual(paths, ["transfer_ownership", "update_tenant"])
