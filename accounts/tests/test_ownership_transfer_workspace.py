"""Workspace + ownership transfer invariants for active tenant/branch."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from access.services.membership_bll import membership_service
from access.services.permission_audit_bll import permission_audit_bll
from accounts.services.workspace_bll import workspace_bll
from accounts.tests.test_active_branch import make_branch, make_owner_user, make_tenant
from core.exceptions import ActiveBranchTenantMismatchException
from tenants.models import Branch
from tenants.selectors import TenantDataAccessLayer
from tenants.services.place_bll import TenantBusinessLogicLayer as PlaceTenantBLL


class ActiveTenantBranchConsistencyTests(TestCase):
    def test_normal_branch_belongs_to_tenant(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)

        self.assertEqual(branch.tenant_id, tenant.id)
        user.active_tenant = tenant
        user.save(update_fields=["active_tenant_id"])
        workspace_bll.set_active_branch(user, branch)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch.id)

    def test_string_tenant_id_switch_still_allows_branch_selection(self):
        """Regression: str vs UUID must not false-trigger mismatch."""
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)

        membership_service.switch_active_tenant(user, str(tenant.id))
        self.assertIsInstance(user.active_tenant_id, uuid.UUID)

        workspace_bll.set_active_branch(user, branch)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch.id)

    def test_uuid_tenant_id_switch_still_allows_branch_selection(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)

        membership_service.switch_active_tenant(user, tenant.id)
        self.assertIsInstance(user.active_tenant_id, uuid.UUID)
        workspace_bll.set_active_branch(user, branch)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch.id)

    def test_switch_branch_rejects_true_tenant_mismatch(self):
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_b = make_branch(tenant_b)
        user.active_tenant = tenant_a
        user.save(update_fields=["active_tenant_id"])

        with self.assertRaises(ActiveBranchTenantMismatchException):
            workspace_bll.set_active_branch(user, branch_b)

    def test_ownership_transfer_keeps_branches_on_same_tenant(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        tenant = make_tenant(old_owner, name="TransferMe")
        branch_a = make_branch(tenant, name="A")
        branch_b = make_branch(tenant, name="B")

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        tenant.refresh_from_db()
        self.assertEqual(tenant.owner_id, new_owner.id)
        branch_a.refresh_from_db()
        branch_b.refresh_from_db()
        self.assertEqual(branch_a.tenant_id, tenant.id)
        self.assertEqual(branch_b.tenant_id, tenant.id)
        self.assertEqual(
            set(Branch.objects.filter(tenant_id=tenant.id).values_list("id", flat=True)),
            {branch_a.id, branch_b.id},
        )

    def test_ownership_transfer_clears_previous_owner_workspace(self):
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        tenant = make_tenant(old_owner)
        branch = make_branch(tenant)
        old_user.active_tenant = tenant
        old_user.active_branch = branch
        old_user.save(update_fields=["active_tenant_id", "active_branch_id"])

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        old_user.refresh_from_db()
        self.assertIsNone(old_user.active_tenant_id)
        self.assertIsNone(old_user.active_branch_id)

    def test_transfer_clears_active_tenant_even_without_active_branch(self):
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        tenant = make_tenant(old_owner)
        old_user.active_tenant = tenant
        old_user.active_branch = None
        old_user.save(update_fields=["active_tenant_id", "active_branch_id"])

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        old_user.refresh_from_db()
        self.assertIsNone(old_user.active_tenant_id)
        self.assertIsNone(old_user.active_branch_id)

    def test_transfer_preserves_workspace_for_unrelated_tenant(self):
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        keep_tenant = make_tenant(old_owner, name="Keep")
        keep_branch = make_branch(keep_tenant)
        transferred = make_tenant(old_owner, name="GiveAway")
        make_branch(transferred)

        old_user.active_tenant = keep_tenant
        old_user.active_branch = keep_branch
        old_user.save(update_fields=["active_tenant_id", "active_branch_id"])

        PlaceTenantBLL.update_tenant(
            tenant_id=transferred.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=transferred.name,
            status=transferred.status,
        )

        old_user.refresh_from_db()
        self.assertEqual(old_user.active_tenant_id, keep_tenant.id)
        self.assertEqual(old_user.active_branch_id, keep_branch.id)

    def test_transfer_clears_stale_branch_pointing_at_transferred_tenant(self):
        """Inconsistent workspace: active_tenant=other, active_branch=transferred."""
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        keep_tenant = make_tenant(old_owner, name="Keep")
        transferred = make_tenant(old_owner, name="GiveAway")
        transferred_branch = make_branch(transferred)

        old_user.active_tenant = keep_tenant
        old_user.active_branch_id = transferred_branch.id
        # Bypass User.clean() to seed the inconsistent state.
        type(old_user).objects.filter(pk=old_user.pk).update(
            active_tenant_id=keep_tenant.id,
            active_branch_id=transferred_branch.id,
        )
        old_user.refresh_from_db()

        PlaceTenantBLL.update_tenant(
            tenant_id=transferred.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=transferred.name,
            status=transferred.status,
        )

        old_user.refresh_from_db()
        self.assertEqual(old_user.active_tenant_id, keep_tenant.id)
        self.assertIsNone(old_user.active_branch_id)

    def test_transfer_does_not_overwrite_new_owner_workspace(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        other_tenant = make_tenant(new_owner, name="Other")
        other_branch = make_branch(other_tenant)
        tenant = make_tenant(old_owner, name="Transferred")
        make_branch(tenant)

        new_user.active_tenant = other_tenant
        new_user.active_branch = other_branch
        new_user.save(update_fields=["active_tenant_id", "active_branch_id"])

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        new_user.refresh_from_db()
        self.assertEqual(new_user.active_tenant_id, other_tenant.id)
        self.assertEqual(new_user.active_branch_id, other_branch.id)

    def test_branch_selection_after_transfer_for_new_owner(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        other_tenant = make_tenant(new_owner, name="Other")
        tenant = make_tenant(old_owner, name="Transferred")
        branch = make_branch(tenant)

        new_user.active_tenant = other_tenant
        new_user.save(update_fields=["active_tenant_id"])

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        membership_service.switch_active_tenant(new_user, str(tenant.id))
        workspace_bll.set_active_branch(new_user, branch)
        new_user.refresh_from_db()
        self.assertEqual(new_user.active_tenant_id, tenant.id)
        self.assertEqual(new_user.active_branch_id, branch.id)

    def test_new_owner_gains_access_via_owner_relation_not_staff_membership(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        tenant = make_tenant(old_owner, name="Transferred")
        branch = make_branch(tenant)

        PlaceTenantBLL.update_tenant(
            tenant_id=tenant.id,
            actor_id=old_user.id,
            owner=new_user.id,
            name=tenant.name,
            status=tenant.status,
        )

        membership_service.switch_active_tenant(new_user, tenant.id)
        workspace_bll.set_active_branch(new_user, branch)
        self.assertTrue(workspace_bll.user_can_access_branch(new_user, branch))

    def test_api_switch_branch_after_string_coerced_tenant_switch(self):
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_b = make_branch(tenant_b)
        user.active_tenant = tenant_a
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        self.assertEqual(
            client.post(
                "/api/authorization/switch-tenant/",
                {"tenantId": str(tenant_b.id)},
                format="json",
            ).status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertEqual(
            client.post(
                "/api/authorization/switch-branch/",
                {"branchId": str(branch_b.id)},
                format="json",
            ).status_code,
            status.HTTP_204_NO_CONTENT,
        )
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch_b.id)

    def test_api_switch_branch_rejects_stale_branch_from_previous_tenant(self):
        """
        True mismatch after tenant switch: active_tenant=B, branch belongs to A.

        Mirrors a frontend race that still holds a previous tenant's branchId
        while the backend active tenant has already moved.
        """
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_a = make_branch(tenant_a)
        make_branch(tenant_b)
        user.active_tenant = tenant_a
        user.save(update_fields=["active_tenant_id"])

        client = APIClient()
        client.force_authenticate(user=user)
        self.assertEqual(
            client.post(
                "/api/authorization/switch-tenant/",
                {"tenantId": str(tenant_b.id)},
                format="json",
            ).status_code,
            status.HTTP_204_NO_CONTENT,
        )

        with self.assertLogs(
            "accounts.services.workspace_bll", level="WARNING"
        ) as logs:
            response = client.post(
                "/api/authorization/switch-branch/",
                {"branchId": str(branch_a.id)},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()["error"]
        self.assertEqual(body["code"], "active_branch_tenant_mismatch")
        diagnostics = body["diagnostics"]
        self.assertEqual(
            diagnostics["raise_source"], "set_active_branch_tenant_id_mismatch"
        )
        self.assertEqual(diagnostics["active_tenant_id"], str(tenant_b.id))
        self.assertEqual(diagnostics["resolved_branch_id"], str(branch_a.id))
        self.assertEqual(diagnostics["resolved_branch_tenant_id"], str(tenant_a.id))
        self.assertFalse(diagnostics["ids_equal"])
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant_b.id)
        self.assertIsNone(user.active_branch_id)
        self.assertTrue(
            any("active_branch_tenant_mismatch" in message for message in logs.output)
        )

    def test_unrelated_full_clean_error_does_not_become_tenant_mismatch(self):
        """
        Case A regression: active_tenant_id == branch.tenant_id must succeed
        even if Model.full_clean would fail on an unrelated field.
        """
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)
        membership_service.switch_active_tenant(user, tenant.id)
        user.refresh_from_db()
        self.assertTrue(
            str(user.active_tenant_id) == str(branch.tenant_id)
        )

        with patch.object(
            type(user),
            "full_clean",
            side_effect=DjangoValidationError({"email": ["already taken"]}),
        ):
            workspace_bll.set_active_branch(user, branch)

        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch.id)

    def test_set_active_branch_uses_locked_db_tenant_not_stale_request_user(self):
        """request.user may be stale; set_active_branch must re-read under lock."""
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_b = make_branch(tenant_b)
        membership_service.switch_active_tenant(user, tenant_b.id)

        # Stale in-memory pointer from an older request snapshot.
        user.active_tenant_id = tenant_a.id
        workspace_bll.set_active_branch(user, branch_b)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant_b.id)
        self.assertEqual(user.active_branch_id, branch_b.id)

    def test_user_clean_after_assignment_sees_new_branch_not_stale_relation(self):
        """
        After locked.active_branch = branch, User.clean() must compare the
        newly assigned branch's tenant — not a previously cached relation.
        """
        user, owner = make_owner_user()
        tenant_a = make_tenant(owner, name="A")
        tenant_b = make_tenant(owner, name="B")
        branch_a = make_branch(tenant_a)
        branch_b = make_branch(tenant_b)

        # Seed inconsistent cached relation: active_tenant=B, cached branch=A.
        user.active_tenant = tenant_b
        user.active_branch = branch_a
        type(user).objects.filter(pk=user.pk).update(
            active_tenant_id=tenant_b.id,
            active_branch_id=branch_a.id,
        )
        user.refresh_from_db()
        # Force-cache the stale relation on the instance.
        _ = user.active_branch
        self.assertEqual(user.active_branch_id, branch_a.id)

        membership_service.switch_active_tenant(user, tenant_b.id)
        # Direct set_active_branch must replace the relation and pass clean().
        workspace_bll.set_active_branch(user, branch_b)
        user.refresh_from_db()
        self.assertEqual(user.active_branch_id, branch_b.id)

    def test_switch_branch_with_null_active_tenant_succeeds(self):
        user, owner = make_owner_user()
        tenant = make_tenant(owner)
        branch = make_branch(tenant)
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/authorization/switch-branch/",
            {"branchId": str(branch.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        diagnostics = response.json().get("error", {}).get("diagnostics")
        self.assertIsNone(diagnostics)
        user.refresh_from_db()
        self.assertEqual(user.active_tenant_id, tenant.id)
        self.assertEqual(user.active_branch_id, branch.id)

    def test_transfer_rollback_restores_previous_owner_workspace(self):
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        tenant = make_tenant(old_owner)
        branch = make_branch(tenant)
        old_user.active_tenant = tenant
        old_user.active_branch = branch
        old_user.save(update_fields=["active_tenant_id", "active_branch_id"])

        with patch.object(
            permission_audit_bll,
            "record_ownership_transfer",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                PlaceTenantBLL.update_tenant(
                    tenant_id=tenant.id,
                    actor_id=old_user.id,
                    owner=new_user.id,
                    name=tenant.name,
                    status=tenant.status,
                )

        old_user.refresh_from_db()
        tenant.refresh_from_db()
        self.assertEqual(tenant.owner_id, old_owner.id)
        self.assertEqual(old_user.active_tenant_id, tenant.id)
        self.assertEqual(old_user.active_branch_id, branch.id)

    def test_transfer_schedules_owner_cache_invalidation_on_commit(self):
        old_user, old_owner = make_owner_user()
        new_user, new_owner = make_owner_user()
        tenant = make_tenant(old_owner, name="Cached")
        make_branch(tenant)

        with patch.object(
            TenantDataAccessLayer, "invalidate_tenant_cache"
        ) as invalidate, patch.object(
            TenantDataAccessLayer, "_refresh_tenant_owner_list_cache"
        ) as refresh_owner_list:
            with self.captureOnCommitCallbacks(execute=True):
                PlaceTenantBLL.update_tenant(
                    tenant_id=tenant.id,
                    actor_id=old_user.id,
                    owner=new_user.id,
                    name=tenant.name,
                    status=tenant.status,
                )

            # Field-save path always invalidates; transfer also invalidates on
            # owner change — both target the previous owner's cache entries.
            self.assertGreaterEqual(invalidate.call_count, 1)
            invalidate.assert_any_call(tenant.id, old_user.id)
            refresh_owner_list.assert_called_once_with(new_user.id)

    def test_update_tenant_owner_unchanged_still_invalidates_cache(self):
        """Field updates must bust tenant cache even when owner stays the same."""
        owner_user, owner = make_owner_user()
        tenant = make_tenant(owner, name="Before")
        make_branch(tenant)

        with patch.object(
            TenantDataAccessLayer, "invalidate_tenant_cache"
        ) as invalidate:
            with self.captureOnCommitCallbacks(execute=True):
                PlaceTenantBLL.update_tenant(
                    tenant_id=tenant.id,
                    actor_id=owner_user.id,
                    owner=owner_user.id,
                    name="After",
                    status=tenant.status,
                )

            invalidate.assert_called_once_with(tenant.id, owner_user.id)

        tenant.refresh_from_db()
        self.assertEqual(tenant.name, "After")
        self.assertEqual(tenant.owner_id, owner.id)

    def test_transfer_rollback_skips_cache_invalidation(self):
        old_user, old_owner = make_owner_user()
        new_user, _ = make_owner_user()
        tenant = make_tenant(old_owner)
        make_branch(tenant)

        with patch.object(
            TenantDataAccessLayer, "invalidate_tenant_cache"
        ) as invalidate, patch.object(
            TenantDataAccessLayer, "_refresh_tenant_owner_list_cache"
        ) as refresh_owner_list, patch.object(
            permission_audit_bll,
            "record_ownership_transfer",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                with self.captureOnCommitCallbacks(execute=True):
                    PlaceTenantBLL.update_tenant(
                        tenant_id=tenant.id,
                        actor_id=old_user.id,
                        owner=new_user.id,
                        name=tenant.name,
                        status=tenant.status,
                    )

            invalidate.assert_not_called()
            refresh_owner_list.assert_not_called()
