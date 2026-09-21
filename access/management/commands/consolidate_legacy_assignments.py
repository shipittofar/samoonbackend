from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from access.services.legacy_assignment_consolidation import run_consolidation


class Command(BaseCommand):
    help = (
        "Maintenance exception: physically merge/delete duplicate ACTIVE/FUTURE "
        "StaffAssignment rows for the same membership+role. Never use Django Admin "
        "delete for assignments. Revoked/expired history rows are not consolidation targets."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report duplicate groups without writing changes.",
        )
        parser.add_argument(
            "--tenant",
            dest="tenant_id",
            help="Only consolidate assignments for the given tenant UUID.",
        )

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        dry_run = options.get("dry_run", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no database writes will be performed."))

        try:
            stats = run_consolidation(tenant_id=tenant_id, dry_run=dry_run)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if not dry_run and stats.affected_membership_ids:
            self._invalidate_affected_permission_caches(stats.affected_membership_ids)

        for plan in stats.plans:
            self.stdout.write(
                "Duplicate group: "
                f"tenant_id={plan.tenant_id} "
                f"membership_id={plan.membership_id} "
                f"role_id={plan.role_id} "
                f"rows_to_merge={len(plan.assignment_ids)} "
                f"survivor_id={plan.survivor_id} "
                f"duplicate_ids={plan.duplicate_ids} "
                f"all_locations={plan.all_locations} "
                f"merged_branch_ids={plan.merged_branch_ids}"
            )

        if stats.errors:
            for error in stats.errors:
                self.stderr.write(self.style.ERROR(error))

        self.stdout.write("")
        self.stdout.write("Summary")
        self.stdout.write(f"  groups found: {stats.groups_found}")
        self.stdout.write(f"  groups merged: {stats.groups_merged}")
        self.stdout.write(f"  assignments deleted: {stats.assignments_deleted}")
        self.stdout.write(f"  locations added: {stats.locations_added}")
        self.stdout.write(f"  skipped groups: {stats.skipped_groups}")
        self.stdout.write(f"  affected memberships: {len(stats.affected_membership_ids)}")
        self.stdout.write(f"  errors: {len(stats.errors)}")

        if dry_run:
            rows_to_merge = sum(len(plan.assignment_ids) for plan in stats.plans)
            self.stdout.write(f"  rows to merge (dry run): {rows_to_merge}")

    @staticmethod
    def _invalidate_affected_permission_caches(membership_ids) -> None:
        """Bust effective-permissions caches for memberships touched by consolidation."""
        from access.models import StaffMembership
        from access.services.rbac_bll import rbac_bll

        memberships = StaffMembership.objects.filter(id__in=membership_ids).only(
            "id", "user_id", "tenant_id"
        )
        for membership in memberships:
            rbac_bll.invalidate_effective_permissions_for_membership(membership)
