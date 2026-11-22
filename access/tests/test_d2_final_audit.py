"""Canonical assignment model, migration integrity, and repository audit."""
import re
from pathlib import Path

from django.apps import apps
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from access.models import StaffAssignment
from access.selectors.permission_dal import permission_selector
from access.services.assignment_bll import assignment_bll
from access.services.assignment_scope import (
    assignment_covers_branch,
    assignment_covers_branch_q,
    resolve_assignment_branch_ids,
)
from access.services.rbac_bll import rbac_bll
from access.tests.helpers import (
    create_canonical_assignment,
    get_role,
    make_branch,
    make_membership,
    make_tenant,
    make_user,
)
from accounts.services.workspace_bll import workspace_bll


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCESS_APP = "access"


class CanonicalAssignmentTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = get_role("manager")
        self.membership = make_membership(user=self.staff_user, tenant=self.tenant)
        self.branch_a = make_branch(self.tenant, name="Branch A")
        self.branch_b = make_branch(self.tenant, name="Branch B")

    def test_single_location_assignment_uses_junction_only(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_id=self.branch_a.id,
        )

        self.assertFalse(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 1)
        field_names = {field.name for field in StaffAssignment._meta.get_fields()}
        self.assertNotIn("branch", field_names)

    def test_multi_location_assignment_works(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id, self.branch_b.id],
        )

        self.assertEqual(assignment.locations.count(), 2)
        self.assertEqual(
            set(assignment.locations.values_list("branch_id", flat=True)),
            {self.branch_a.id, self.branch_b.id},
        )

    def test_tenant_wide_assignment_works(self):
        assignment = assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            all_locations=True,
        )

        self.assertTrue(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 0)
        self.assertEqual(resolve_assignment_branch_ids(assignment), "all")

    def test_scope_helpers_use_junction_locations(self):
        assignment = create_canonical_assignment(
            membership=self.membership,
            role=self.manager_role,
            branch=self.branch_a,
        )

        self.assertEqual(resolve_assignment_branch_ids(assignment), [str(self.branch_a.id)])
        self.assertTrue(assignment_covers_branch(assignment, self.branch_a.id))
        self.assertFalse(assignment_covers_branch(assignment, self.branch_b.id))
        self.assertTrue(
            StaffAssignment.objects.filter(id=assignment.id)
            .filter(assignment_covers_branch_q(branch_id=self.branch_a.id))
            .exists()
        )

    def test_assignment_defaults(self):
        assignment = create_canonical_assignment(
            membership=self.membership,
            role=self.manager_role,
            branch=self.branch_a,
        )
        self.assertEqual(assignment.mode, "manage")
        self.assertEqual(assignment.status, "active")
        self.assertIsNone(assignment.granted_by_id)
        self.assertIsNone(assignment.granted_at)

    def test_permission_resolution_unchanged(self):
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id],
        )

        slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=self.branch_a.id,
        )
        self.assertIn("staff.view", slugs)

    def test_workspace_access_unchanged(self):
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            branch_ids=[self.branch_a.id, self.branch_b.id],
        )

        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_a))
        self.assertTrue(workspace_bll.user_can_access_branch(self.staff_user, self.branch_b))

    def test_rbac_effective_permissions_for_tenant_wide_staff(self):
        assignment_bll.create_assignment(
            membership_id=self.membership.id,
            role_id=self.manager_role.id,
            all_locations=True,
        )

        permissions = rbac_bll.get_effective_permissions(
            user=self.staff_user,
            tenant=self.tenant,
        )
        self.assertIn("staff.view", permissions)


class MigrationAuditTests(TestCase):
    EXPECTED_ACCESS_MIGRATIONS = (
        "0001_initial",
        "0002_initial",
        "0003_seed_analytics_permissions",
        "0004_seed_settings_permissions",
        "0005_seed_rbac_reference_data",
        "0006_staff_assignment_additive_fields",
        "0007_staff_assignment_location",
        "0008_backfill_assignment_locations",
        "0009_drop_legacy_assignment_uniqueness",
        "0010_audit_duplicate_active_role_grants",
        "0011_add_non_terminal_membership_role_grant_unique",
        "0012_remove_staffassignment_branch",
        "0013_rename_staff_assig_members_7f0a2a_idx_staff_assig_members_3e88f2_idx_and_more",
        "0014_permission_override_and_audit",
        "0015_seed_rbac_manage_roles_permission",
        "0016_remove_manage_roles_from_owner",
        "0017_alter_permissionaudit_action",
        "0018_lifecycle_fk_safety",
    )

    def test_access_migration_chain_is_linear_to_head(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        access_nodes = sorted(
            node[1] for node in loader.graph.nodes if node[0] == ACCESS_APP
        )
        self.assertEqual(access_nodes, list(self.EXPECTED_ACCESS_MIGRATIONS))

        for index in range(1, len(self.EXPECTED_ACCESS_MIGRATIONS)):
            migration = loader.get_migration(
                ACCESS_APP, self.EXPECTED_ACCESS_MIGRATIONS[index]
            )
            access_dependencies = [
                dependency
                for dependency in migration.dependencies
                if dependency[0] == ACCESS_APP
            ]
            self.assertEqual(
                access_dependencies,
                [(ACCESS_APP, self.EXPECTED_ACCESS_MIGRATIONS[index - 1])],
            )

    def test_staff_assignment_model_has_no_branch_field(self):
        field_names = {field.name for field in StaffAssignment._meta.get_fields()}
        self.assertNotIn("branch", field_names)

    def test_staff_assignment_constraints_match_final_model(self):
        constraint_names = {
            constraint.name for constraint in StaffAssignment._meta.constraints
        }
        self.assertIn("unique_non_terminal_membership_role_grant", constraint_names)
        self.assertNotIn("all_locations_implies_null_branch_mirror", constraint_names)


class RepositoryAuditTests(TestCase):
    _SCAN_ROOTS = (
        "access",
        "accounts",
        "tenants/selectors/branch_metrics_dal.py",
        "website_builder",
    )

    def _rg(self, pattern: str) -> str:
        """Search repo sources without depending on the ripgrep binary."""
        regex = re.compile(pattern)
        hits: list[str] = []
        for root in self._SCAN_ROOTS:
            path = REPO_ROOT / root
            files = [path] if path.is_file() else sorted(path.rglob("*.py"))
            for file_path in files:
                if not file_path.is_file():
                    continue
                parts = file_path.parts
                if "migrations" in parts or "tests" in parts:
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        rel = file_path.relative_to(REPO_ROOT)
                        hits.append(f"{rel}:{line_no}:{line}")
        return "\n".join(hits)

    def test_no_assignment_branch_mirror_references(self):
        self.assertEqual(self._rg(r"assignment\.branch(_id)?|obj\.branch_id"), "")

    def test_no_dual_read_or_compatibility_scope_references(self):
        self.assertEqual(
            self._rg(r"dual-read|dual_read|branch mirror|compatibility fallback"),
            "",
        )

    def test_consolidation_command_module_still_present(self):
        command = apps.get_app_config(ACCESS_APP).module
        command_path = (
            Path(command.__file__).parent
            / "management/commands/consolidate_legacy_assignments.py"
        )
        self.assertTrue(command_path.exists())
