from __future__ import annotations

from django.db.models import Q, QuerySet

from access.models import AssignmentStatus, StaffAssignment

AUTHORIZATION_ASSIGNMENT_STATUSES = (
    AssignmentStatus.ACTIVE,
    AssignmentStatus.FUTURE,
)


def filter_assignments_for_authorization(
    queryset: QuerySet[StaffAssignment],
) -> QuerySet[StaffAssignment]:
    """Assignments that may participate in permission and branch-access resolution."""
    return queryset.filter(status__in=AUTHORIZATION_ASSIGNMENT_STATUSES)


def assignment_is_authorizable(assignment: StaffAssignment) -> bool:
    return assignment.status in AUTHORIZATION_ASSIGNMENT_STATUSES


def assignment_is_tenant_wide(assignment: StaffAssignment) -> bool:
    """True when the assignment applies tenant-wide (all locations)."""
    return assignment.all_locations


def assignment_covers_branch(assignment: StaffAssignment, branch_id) -> bool:
    if not assignment_is_authorizable(assignment):
        return False
    if assignment.all_locations:
        return True
    return assignment.locations.filter(branch_id=branch_id).exists()


def assignment_covers_branch_q(*, branch_id) -> Q:
    """ORM filter for assignments covering a specific branch."""
    return Q(all_locations=True) | Q(locations__branch_id=branch_id)


def filter_assignments_tenant_wide(
    queryset: QuerySet[StaffAssignment],
) -> QuerySet[StaffAssignment]:
    """Assignments that apply tenant-wide."""
    return queryset.filter(all_locations=True).distinct()


def filter_assignments_covering_branch(
    queryset: QuerySet[StaffAssignment],
    *,
    branch_id,
) -> QuerySet[StaffAssignment]:
    """Assignments whose scope includes the given branch."""
    return queryset.filter(assignment_covers_branch_q(branch_id=branch_id)).distinct()


def filter_assignments_in_scope(
    queryset: QuerySet[StaffAssignment],
    *,
    branch_id=None,
) -> QuerySet[StaffAssignment]:
    """Single entry point for membership assignment scope queries."""
    if branch_id is None:
        return filter_assignments_tenant_wide(queryset)
    return filter_assignments_covering_branch(queryset, branch_id=branch_id)


def membership_has_tenant_wide_scope(assignments) -> bool:
    """Whether any assignment grants tenant-wide branch access."""
    if hasattr(assignments, "prefetch_related"):
        iterable = assignments.prefetch_related("locations")
    else:
        iterable = assignments

    for assignment in iterable:
        if not assignment_is_authorizable(assignment):
            continue
        if assignment_is_tenant_wide(assignment):
            return True
    return False


def membership_covers_branch(assignments, branch_id) -> bool:
    """Whether any assignment grants access to the given branch."""
    if hasattr(assignments, "prefetch_related"):
        iterable = assignments.prefetch_related("locations")
    else:
        iterable = assignments

    for assignment in iterable:
        if not assignment_is_authorizable(assignment):
            continue
        if assignment_covers_branch(assignment, branch_id):
            return True
    return False


def collect_accessible_branch_ids(assignments) -> set | None:
    """
    Return None when tenant-wide; otherwise the union of scoped branch IDs.
    """
    if hasattr(assignments, "prefetch_related"):
        iterable = assignments.prefetch_related("locations")
    else:
        iterable = assignments

    if membership_has_tenant_wide_scope(iterable):
        return None

    branch_ids: set = set()
    for assignment in iterable:
        if not assignment_is_authorizable(assignment):
            continue
        if assignment_is_tenant_wide(assignment):
            return None
        branch_ids.update(assignment.locations.values_list("branch_id", flat=True))
    return branch_ids


def resolve_assignment_branch_ids(assignment: StaffAssignment) -> list[str] | str:
    """Wire-format branchIds for session payloads."""
    if assignment.all_locations:
        return "all"

    return [
        str(branch_id)
        for branch_id in assignment.locations.values_list("branch_id", flat=True)
    ]
