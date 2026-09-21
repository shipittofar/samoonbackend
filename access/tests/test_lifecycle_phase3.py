"""Phase 3 lifecycle policy: tenant, membership, assignment, audit, FK safety."""
import uuid

from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from access.models import (
    AssignmentMode,
    AssignmentStatus,
    PermissionAudit,
    PermissionAuditAction,
    Role,
    StaffAssignment,
    StaffAssignmentLocation,
    StaffMembership,
    StaffMembershipStatus,
)
from access.services.assignment_bll import assignment_bll
from access.services.membership_bll import membership_service
from access.tests.helpers import get_role, make_branch, make_membership, make_tenant, make_user
from tenants.models import Tenant, TenantStatus
from tenants.services.tenant_bll import TenantBusinessLogicLayer


class MembershipLifecycleTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.user = make_user()
        self.membership = make_membership(user=self.user, tenant=self.tenant)
        self.role = get_role("manager")
        self.waiter = get_role("waiter")
        self.branch = make_branch(self.tenant)

    def test_remove_revokes_active_future_preserves_rows_and_locations(self):
        active = StaffAssignment.objects.create(
            membership=self.membership,
            role=self.role,
            all_locations=True,
            status=AssignmentStatus.ACTIVE,
            mode=AssignmentMode.MANAGE,
        )
        future = StaffAssignment.objects.create(
            membership=self.membership,
            role=self.waiter,
            all_locations=False,
            status=AssignmentStatus.FUTURE,
            mode=AssignmentMode.READ,
        )
        StaffAssignmentLocation.objects.create(assignment=future, branch=self.branch)
        expired = StaffAssignment.objects.create(
            membership=self.membership,
            role=Role.objects.get(slug="cashier"),
            all_locations=True,
            status=AssignmentStatus.EXPIRED,
            mode=AssignmentMode.READ,
        )
        revoked = StaffAssignment.objects.create(
            membership=self.membership,
            role=Role.objects.get(slug="kitchen"),
            all_locations=True,
            status=AssignmentStatus.REVOKED,
            mode=AssignmentMode.READ,
        )

        membership_service.remove_membership(
            tenant_id=self.tenant.id, membership_id=self.membership.id
        )
        membership_service.remove_membership(
            tenant_id=self.tenant.id, membership_id=self.membership.id
        )

        self.membership.refresh_from_db()
        active.refresh_from_db()
        future.refresh_from_db()
        expired.refresh_from_db()
        revoked.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(active.status, AssignmentStatus.REVOKED)
        self.assertEqual(future.status, AssignmentStatus.REVOKED)
        self.assertEqual(expired.status, AssignmentStatus.EXPIRED)
        self.assertEqual(revoked.status, AssignmentStatus.REVOKED)
        self.assertEqual(StaffAssignment.objects.filter(membership=self.membership).count(), 4)
        self.assertTrue(StaffAssignmentLocation.objects.filter(assignment=future).exists())
        self.assertTrue(
            PermissionAudit.objects.filter(
                action=PermissionAuditAction.MEMBERSHIP_REMOVED,
                membership=self.membership,
            ).exists()
        )

    def test_duplicate_membership_blocked_and_removed_can_restore(self):
        with self.assertRaises(ValidationError):
            membership_service.create_membership(
                tenant_id=self.tenant.id, user_id=self.user.id
            )

        membership_service.remove_membership(
            tenant_id=self.tenant.id, membership_id=self.membership.id
        )
        assignment = StaffAssignment.objects.create(
            membership=self.membership,
            role=self.role,
            all_locations=True,
            status=AssignmentStatus.REVOKED,
            mode=AssignmentMode.MANAGE,
        )

        restored = membership_service.create_membership(
            tenant_id=self.tenant.id, user_id=self.user.id
        )
        self.assertEqual(restored.id, self.membership.id)
        self.assertEqual(restored.status, StaffMembershipStatus.ACTIVE)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)

        new_assignment = assignment_bll.create_assignment(
            membership_id=restored.id,
            role_id=self.role.id,
            branch_ids=[],
            all_locations=True,
        )
        self.assertEqual(new_assignment.status, AssignmentStatus.ACTIVE)
        self.assertNotEqual(new_assignment.id, assignment.id)

        with self.assertRaises((ValidationError, IntegrityError)):
            from django.db import transaction as db_transaction

            with db_transaction.atomic():
                StaffMembership.objects.create(user=self.user, tenant=self.tenant)

    def test_assignment_revoke_is_idempotent_and_preserves_row(self):
        assignment = StaffAssignment.objects.create(
            membership=self.membership,
            role=self.role,
            all_locations=True,
            status=AssignmentStatus.ACTIVE,
            mode=AssignmentMode.MANAGE,
        )
        assignment_bll.revoke_assignment(assignment_id=assignment.id, revoked_by_id=None)
        assignment_bll.revoke_assignment(assignment_id=assignment.id, revoked_by_id=None)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_membership_and_assignment_fk_protect(self):
        StaffAssignment.objects.create(
            membership=self.membership,
            role=self.role,
            all_locations=True,
            status=AssignmentStatus.ACTIVE,
            mode=AssignmentMode.MANAGE,
        )
        with self.assertRaises(ProtectedError):
            self.membership.delete()
        with self.assertRaises(ProtectedError):
            self.tenant.delete()


class TenantLifecycleTests(TestCase):
    def test_deactivate_sets_flags_removes_memberships_keeps_audit(self):
        owner, tenant = make_tenant()
        user = make_user()
        membership = make_membership(user=user, tenant=tenant)
        assignment = StaffAssignment.objects.create(
            membership=membership,
            role=get_role("manager"),
            all_locations=True,
            status=AssignmentStatus.ACTIVE,
            mode=AssignmentMode.MANAGE,
        )
        audit = PermissionAudit.objects.create(
            tenant=tenant,
            action=PermissionAuditAction.ASSIGNMENT_CREATED,
            metadata={},
        )

        TenantBusinessLogicLayer.delete_tenant(user=owner, tenant_id=tenant.id)
        TenantBusinessLogicLayer.delete_tenant(user=owner, tenant_id=tenant.id)

        tenant.refresh_from_db()
        membership.refresh_from_db()
        assignment.refresh_from_db()
        audit.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)
        self.assertFalse(tenant.is_active)
        self.assertEqual(membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())
        self.assertTrue(PermissionAudit.objects.filter(id=audit.id).exists())
        self.assertEqual(audit.tenant_id, tenant.id)
        self.assertTrue(
            PermissionAudit.objects.filter(
                action=PermissionAuditAction.TENANT_DEACTIVATED,
                tenant=tenant,
            ).exists()
        )

    def test_permission_audit_tenant_set_null_on_hard_delete_without_memberships(self):
        owner, tenant = make_tenant()
        audit = PermissionAudit.objects.create(
            tenant=tenant,
            action=PermissionAuditAction.ASSIGNMENT_CREATED,
            metadata={},
        )
        tenant.delete()
        audit.refresh_from_db()
        self.assertIsNone(audit.tenant_id)
