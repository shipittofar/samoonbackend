"""Tests for consolidate_legacy_assignments management command."""
import uuid
from contextlib import contextmanager
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from access.models import (
    AssignmentStatus,
    Role,
    StaffAssignment,
    StaffAssignmentLocation,
    StaffMembership,
    StaffMembershipStatus,
)
from access.services.legacy_assignment_consolidation import find_duplicate_groups, run_consolidation
from access.tests.helpers import create_canonical_assignment
from accounts.models import User
from tenants.models import Branch, Owner, Tenant, TenantStatus

CONSTRAINT_NAME = "unique_non_terminal_membership_role_grant"
CONSTRAINT_INDEX_SQL = (
    'CREATE UNIQUE INDEX "unique_non_terminal_membership_role_grant" '
    'ON "staff_assignment" ("membership_id", "role_id") '
    'WHERE "status" IN (\'active\', \'future\')'
)


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


def make_tenant(**kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return owner_user, tenant


@contextmanager
def legacy_duplicate_grants_allowed():
    """
    Legacy production databases may predate unique_non_terminal_membership_role_grant.
    Tests simulate that state by temporarily dropping the partial unique index.
    """
    with connection.cursor() as cursor:
        cursor.execute(f'DROP INDEX IF EXISTS "{CONSTRAINT_NAME}"')
    try:
        yield
    finally:
        while find_duplicate_groups().exists():
            run_consolidation()
        with connection.cursor() as cursor:
            cursor.execute(CONSTRAINT_INDEX_SQL)


def create_scoped_assignment(*, membership, role, branch, granted_by=None):
    return create_canonical_assignment(
        membership=membership,
        role=role,
        branch=branch,
        granted_by=granted_by,
    )


class ConsolidateLegacyAssignmentsTests(TestCase):
    def setUp(self):
        self.granter, self.tenant = make_tenant()
        self.other_granter, self.other_tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.other_membership = StaffMembership.objects.create(
            user=make_user(),
            tenant=self.other_tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(tenant=self.tenant, name="Branch A")
        self.branch_b = Branch.objects.create(tenant=self.tenant, name="Branch B")
        self.branch_c = Branch.objects.create(tenant=self.tenant, name="Branch C")
        self.other_branch = Branch.objects.create(
            tenant=self.other_tenant,
            name="Other Branch",
        )

    def _call_command(self, *args):
        stdout = StringIO()
        stderr = StringIO()
        call_command(
            "consolidate_legacy_assignments",
            *args,
            stdout=stdout,
            stderr=stderr,
        )
        return stdout.getvalue(), stderr.getvalue()

    def _assignment_state_snapshot(self):
        return sorted(
            (
                str(assignment.id),
                str(assignment.membership_id),
                str(assignment.role_id),
                assignment.status,
                assignment.all_locations,
                sorted(
                    str(branch_id)
                    for branch_id in assignment.locations.values_list(
                        "branch_id", flat=True
                    )
                ),
            )
            for assignment in StaffAssignment.objects.prefetch_related("locations")
        )

    def test_no_duplicates_makes_no_changes(self):
        create_scoped_assignment(
            membership=self.membership,
            role=self.manager_role,
            branch=self.branch_a,
        )

        stats = run_consolidation()

        self.assertEqual(stats.groups_found, 0)
        self.assertEqual(stats.groups_merged, 0)
        self.assertEqual(StaffAssignment.objects.count(), 1)

    def test_manager_a_and_manager_b_become_one_assignment_with_two_locations(self):
        with legacy_duplicate_grants_allowed():
            first = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
                granted_by=self.granter,
            )
            second = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
                granted_by=self.granter,
            )

            stats = run_consolidation()

        self.assertEqual(stats.groups_found, 1)
        self.assertEqual(stats.groups_merged, 1)
        self.assertEqual(stats.assignments_deleted, 1)
        self.assertEqual(StaffAssignment.objects.count(), 1)

        survivor = StaffAssignment.objects.get()
        self.assertEqual(survivor.id, first.id)
        self.assertFalse(survivor.all_locations)
        self.assertEqual(
            set(survivor.locations.values_list("branch_id", flat=True)),
            {self.branch_a.id, self.branch_b.id},
        )
        self.assertFalse(StaffAssignment.objects.filter(id=second.id).exists())

    def test_three_duplicate_rows_are_all_merged(self):
        with legacy_duplicate_grants_allowed():
            first = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_c,
            )

            stats = run_consolidation()

        self.assertEqual(stats.groups_merged, 1)
        self.assertEqual(stats.assignments_deleted, 2)
        self.assertEqual(StaffAssignment.objects.count(), 1)

        survivor = StaffAssignment.objects.get(id=first.id)
        self.assertEqual(survivor.locations.count(), 3)

    def test_dry_run_reports_without_database_mutation(self):
        with legacy_duplicate_grants_allowed():
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )

            stats = run_consolidation(dry_run=True)

            self.assertEqual(stats.groups_found, 1)
            self.assertEqual(stats.groups_merged, 0)
            self.assertEqual(StaffAssignment.objects.count(), 2)

            stdout, _ = self._call_command("--dry-run")
            self.assertIn("Dry run", stdout)
            self.assertIn("rows to merge (dry run): 2", stdout)

    def test_already_consolidated_assignment_is_no_op(self):
        assignment = create_scoped_assignment(
            membership=self.membership,
            role=self.manager_role,
            branch=self.branch_a,
        )
        StaffAssignmentLocation.objects.get_or_create(
            assignment=assignment,
            branch=self.branch_a,
        )

        stats = run_consolidation()

        self.assertEqual(stats.groups_found, 0)
        self.assertEqual(StaffAssignment.objects.count(), 1)

    def test_tenant_filter_only_changes_selected_tenant(self):
        with legacy_duplicate_grants_allowed():
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )
            create_scoped_assignment(
                membership=self.other_membership,
                role=self.manager_role,
                branch=self.other_branch,
            )
            create_scoped_assignment(
                membership=self.other_membership,
                role=self.manager_role,
                branch=self.other_branch,
            )

            stats = run_consolidation(tenant_id=self.tenant.id)

            self.assertEqual(stats.groups_merged, 1)
            self.assertEqual(
                StaffAssignment.objects.filter(membership__tenant=self.tenant).count(),
                1,
            )
            self.assertEqual(
                StaffAssignment.objects.filter(membership__tenant=self.other_tenant).count(),
                2,
            )

    def test_multiple_roles_are_consolidated_independently(self):
        with legacy_duplicate_grants_allowed():
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.waiter_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.waiter_role,
                branch=self.branch_b,
            )

            stats = run_consolidation()

        self.assertEqual(stats.groups_found, 2)
        self.assertEqual(stats.groups_merged, 2)
        self.assertEqual(StaffAssignment.objects.count(), 2)
        self.assertEqual(
            StaffAssignment.objects.filter(role=self.manager_role).get().locations.count(),
            2,
        )
        self.assertEqual(
            StaffAssignment.objects.filter(role=self.waiter_role).get().locations.count(),
            2,
        )

    def test_revoked_rows_are_ignored(self):
        with legacy_duplicate_grants_allowed():
            active_a = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            active_b = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )
            revoked = StaffAssignment.objects.create(
                membership=self.membership,
                role=self.manager_role,
                all_locations=False,
                status=AssignmentStatus.REVOKED,
            )
            StaffAssignmentLocation.objects.create(
                assignment=revoked,
                branch=self.branch_c,
            )

            stats = run_consolidation()

        self.assertEqual(stats.groups_merged, 1)
        self.assertEqual(StaffAssignment.objects.count(), 2)
        self.assertTrue(StaffAssignment.objects.filter(id=revoked.id).exists())
        survivor = StaffAssignment.objects.get(
            id__in=[active_a.id, active_b.id],
            status=AssignmentStatus.ACTIVE,
        )
        self.assertEqual(survivor.locations.count(), 2)

    def test_expired_rows_are_ignored(self):
        with legacy_duplicate_grants_allowed():
            active = create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )
            expired = StaffAssignment.objects.create(
                membership=self.membership,
                role=self.manager_role,
                all_locations=False,
                status=AssignmentStatus.EXPIRED,
            )
            StaffAssignmentLocation.objects.create(
                assignment=expired,
                branch=self.branch_c,
            )

            stats = run_consolidation()

        self.assertEqual(stats.groups_merged, 1)
        self.assertEqual(StaffAssignment.objects.count(), 2)
        self.assertTrue(StaffAssignment.objects.filter(id=expired.id).exists())
        self.assertEqual(StaffAssignment.objects.get(id=active.id).locations.count(), 2)

    def test_idempotency_second_run_is_no_op(self):
        with legacy_duplicate_grants_allowed():
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )

            first_stats = run_consolidation()
            snapshot_after_first = self._assignment_state_snapshot()
            second_stats = run_consolidation()
            snapshot_after_second = self._assignment_state_snapshot()

        self.assertEqual(first_stats.groups_merged, 1)
        self.assertEqual(second_stats.groups_found, 0)
        self.assertEqual(second_stats.groups_merged, 0)
        self.assertEqual(snapshot_after_first, snapshot_after_second)

    def test_command_summary_output(self):
        with legacy_duplicate_grants_allowed():
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_a,
            )
            create_scoped_assignment(
                membership=self.membership,
                role=self.manager_role,
                branch=self.branch_b,
            )

            stdout, _ = self._call_command()

            self.assertIn("groups found: 1", stdout)
            self.assertIn("groups merged: 1", stdout)
            self.assertIn("assignments deleted: 1", stdout)
