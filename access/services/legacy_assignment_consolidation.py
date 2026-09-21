"""One approved StaffAssignment physical-delete exception.

Normal product/Admin paths must revoke assignments, never delete them.
This module is invoked only by the `consolidate_legacy_assignments` management
command. It physically deletes true duplicate ACTIVE/FUTURE assignment rows
(same membership+role) after merging locations onto a single survivor.
Revoked/expired history is never a consolidation target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from django.db import transaction
from django.db.models import Count, QuerySet

from access.models import AssignmentMode, AssignmentStatus, StaffAssignment
from access.services.assignment_bll import assignment_bll
from access.services.assignment_scope import AUTHORIZATION_ASSIGNMENT_STATUSES

NON_TERMINAL_STATUSES = AUTHORIZATION_ASSIGNMENT_STATUSES


@dataclass
class DuplicateGroupPlan:
    membership_id: UUID
    role_id: UUID
    tenant_id: UUID
    assignment_ids: list[UUID]
    survivor_id: UUID
    duplicate_ids: list[UUID]
    all_locations: bool
    merged_branch_ids: list
    locations_to_add: int


@dataclass
class ConsolidationStats:
    groups_found: int = 0
    groups_merged: int = 0
    assignments_deleted: int = 0
    locations_added: int = 0
    skipped_groups: int = 0
    errors: list[str] = field(default_factory=list)
    affected_membership_ids: set = field(default_factory=set)
    plans: list[DuplicateGroupPlan] = field(default_factory=list)


def find_duplicate_groups(*, tenant_id=None) -> QuerySet:
    """Return (membership_id, role_id) groups with more than one ACTIVE/FUTURE row."""
    queryset = StaffAssignment.objects.filter(status__in=NON_TERMINAL_STATUSES)
    if tenant_id is not None:
        queryset = queryset.filter(membership__tenant_id=tenant_id)

    return (
        queryset.values("membership_id", "role_id")
        .annotate(assignment_count=Count("id"))
        .filter(assignment_count__gt=1)
        .order_by("membership_id", "role_id")
    )


def _collect_branch_scope(assignment: StaffAssignment) -> tuple[set, bool]:
    """Return branch IDs and whether the row is tenant-wide."""
    if assignment.all_locations:
        return set(), True

    branch_ids = set(assignment.locations.values_list("branch_id", flat=True))
    return branch_ids, False


def _choose_survivor(assignments: list[StaffAssignment]) -> StaffAssignment:
    # Survivor: earliest created_at; tie-break on lowest UUID string for determinism.
    return min(assignments, key=lambda assignment: (assignment.created_at, str(assignment.id)))


def _merge_metadata_fields(assignments: Iterable[StaffAssignment]) -> dict:
    """
    Metadata preservation rules (deterministic):
    - created_at: survivor keeps its own (earliest created_at row is the survivor)
    - updated_at: newest updated_at across the group
    - granted_by / granted_at: from the row with the earliest non-null granted_at;
      if none have granted_at, first non-null granted_by in created_at order
    - valid_from: earliest non-null valid_from
    - valid_until: latest non-null valid_until
    - status: ACTIVE when any row is ACTIVE, otherwise FUTURE
    - mode: MANAGE when any row is MANAGE, otherwise READ
    """
    ordered = sorted(assignments, key=lambda assignment: (assignment.created_at, str(assignment.id)))

    updated_at = max(assignment.updated_at for assignment in ordered)

    granted_candidates = [
        assignment
        for assignment in ordered
        if assignment.granted_at is not None
    ]
    if granted_candidates:
        grant_source = min(
            granted_candidates,
            key=lambda assignment: (assignment.granted_at, str(assignment.id)),
        )
        granted_by_id = grant_source.granted_by_id
        granted_at = grant_source.granted_at
    else:
        grant_source = next(
            (assignment for assignment in ordered if assignment.granted_by_id),
            ordered[0],
        )
        granted_by_id = grant_source.granted_by_id
        granted_at = grant_source.granted_at

    valid_from_values = [assignment.valid_from for assignment in ordered if assignment.valid_from]
    valid_until_values = [assignment.valid_until for assignment in ordered if assignment.valid_until]

    status = (
        AssignmentStatus.ACTIVE
        if any(assignment.status == AssignmentStatus.ACTIVE for assignment in ordered)
        else AssignmentStatus.FUTURE
    )
    mode = (
        AssignmentMode.MANAGE
        if any(assignment.mode == AssignmentMode.MANAGE for assignment in ordered)
        else AssignmentMode.READ
    )

    metadata = {
        "updated_at": updated_at,
        "granted_by_id": granted_by_id,
        "granted_at": granted_at,
        "status": status,
        "mode": mode,
    }
    if valid_from_values:
        metadata["valid_from"] = min(valid_from_values)
    if valid_until_values:
        metadata["valid_until"] = max(valid_until_values)
    return metadata


def plan_duplicate_group(
    *,
    membership_id,
    role_id,
) -> DuplicateGroupPlan | None:
    assignments = list(
        StaffAssignment.objects.filter(
            membership_id=membership_id,
            role_id=role_id,
            status__in=NON_TERMINAL_STATUSES,
        )
        .select_related("membership__tenant")
        .prefetch_related("locations")
        .order_by("created_at", "id")
    )
    if len(assignments) < 2:
        return None

    survivor = _choose_survivor(assignments)
    duplicates = [assignment for assignment in assignments if assignment.id != survivor.id]

    merged_branch_ids: set = set()
    all_locations = False
    for assignment in assignments:
        branch_ids, is_tenant_wide = _collect_branch_scope(assignment)
        if is_tenant_wide:
            all_locations = True
        merged_branch_ids.update(branch_ids)

    existing_branch_ids = set(survivor.locations.values_list("branch_id", flat=True))

    if all_locations:
        locations_to_add = 0
        resolved_branch_ids: list = []
    else:
        resolved_branch_ids, _ = assignment_bll._resolve_location_scope(
            membership=survivor.membership,
            branch_id=None,
            branch_ids=sorted(merged_branch_ids, key=str),
            all_locations=False,
        )
        locations_to_add = len(set(resolved_branch_ids) - existing_branch_ids)

    return DuplicateGroupPlan(
        membership_id=membership_id,
        role_id=role_id,
        tenant_id=survivor.membership.tenant_id,
        assignment_ids=[assignment.id for assignment in assignments],
        survivor_id=survivor.id,
        duplicate_ids=[assignment.id for assignment in duplicates],
        all_locations=all_locations,
        merged_branch_ids=resolved_branch_ids if not all_locations else [],
        locations_to_add=locations_to_add,
    )


def consolidate_duplicate_group(plan: DuplicateGroupPlan) -> int:
    """Merge one duplicate group atomically. Returns locations added."""
    assignments = list(
        StaffAssignment.objects.filter(id__in=plan.assignment_ids)
        .select_related("membership__tenant")
        .prefetch_related("locations")
        .order_by("created_at", "id")
    )
    if len(assignments) < 2:
        return 0

    survivor = next(assignment for assignment in assignments if assignment.id == plan.survivor_id)
    duplicate_ids = [assignment.id for assignment in assignments if assignment.id != survivor.id]

    merged_branch_ids: set = set()
    all_locations = False
    for assignment in assignments:
        branch_ids, is_tenant_wide = _collect_branch_scope(assignment)
        if is_tenant_wide:
            all_locations = True
        merged_branch_ids.update(branch_ids)

    metadata = _merge_metadata_fields(assignments)
    before_location_count = survivor.locations.count()

    with transaction.atomic():
        if all_locations:
            resolved_branch_ids: list = []
            resolved_all_locations = True
            survivor.all_locations = True
        else:
            resolved_branch_ids, resolved_all_locations = assignment_bll._resolve_location_scope(
                membership=survivor.membership,
                branch_id=None,
                branch_ids=sorted(merged_branch_ids, key=str),
                all_locations=False,
            )
            survivor.all_locations = resolved_all_locations

        for field_name, value in metadata.items():
            setattr(survivor, field_name, value)

        survivor.save()
        assignment_bll._sync_scope_after_save(
            assignment=survivor,
            resolved_all_locations=resolved_all_locations,
            resolved_branch_ids=resolved_branch_ids,
        )

        deleted_count, _ = StaffAssignment.objects.filter(id__in=duplicate_ids).delete()
        if deleted_count == 0:
            raise RuntimeError(
                f"Expected to delete duplicate assignments for survivor {survivor.id}"
            )

    survivor.refresh_from_db()
    return max(survivor.locations.count() - before_location_count, 0)


def run_consolidation(*, tenant_id=None, dry_run: bool = False) -> ConsolidationStats:
    stats = ConsolidationStats()
    duplicate_groups = list(find_duplicate_groups(tenant_id=tenant_id))
    stats.groups_found = len(duplicate_groups)

    for group in duplicate_groups:
        membership_id = group["membership_id"]
        role_id = group["role_id"]
        stats.affected_membership_ids.add(membership_id)

        try:
            plan = plan_duplicate_group(
                membership_id=membership_id,
                role_id=role_id,
            )
        except Exception as exc:
            stats.skipped_groups += 1
            stats.errors.append(
                f"membership_id={membership_id} role_id={role_id}: planning failed: {exc}"
            )
            continue

        if plan is None:
            stats.skipped_groups += 1
            continue

        stats.plans.append(plan)

        if dry_run:
            continue

        try:
            locations_added = consolidate_duplicate_group(plan)
        except Exception as exc:
            stats.skipped_groups += 1
            stats.errors.append(
                f"membership_id={membership_id} role_id={role_id}: merge failed: {exc}"
            )
            continue

        stats.groups_merged += 1
        stats.assignments_deleted += len(plan.duplicate_ids)
        stats.locations_added += locations_added

    return stats
