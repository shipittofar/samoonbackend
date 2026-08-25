# RBAC D2 Architecture — Staff Assignment & Authorization

Internal developer reference for the completed D2 migration. This document
describes the canonical data model and runtime behavior after Wave 2.

## Data model

### StaffMembership

One row per `(user, tenant)` pair. Holds membership lifecycle (`pending`,
`active`, `suspended`, `removed`) but not role or location scope.

### StaffAssignment

One row per **role grant** per membership. A user may hold multiple
assignments (different roles) but at most one **non-terminal** assignment per
role (`unique_non_terminal_membership_role_grant`).

| Field | Purpose |
|-------|---------|
| `role` | Granted RBAC role (never `owner`) |
| `all_locations` | `True` = tenant-wide scope |
| `mode` | `read` or `manage` |
| `status` | `active`, `future`, `revoked`, `expired` |
| `valid_from` / `valid_until` | Optional time bounds |
| `granted_by` / `granted_at` | Audit trail |
| `revoked_by` / `revoked_at` | Soft-revoke audit trail |

**Location scope is not stored on `StaffAssignment`.** Scoped locations live
exclusively in `StaffAssignmentLocation`.

### StaffAssignmentLocation

Junction table: `(assignment, branch)`. Unique per pair. Empty when
`all_locations=True`.

## Assignment lifecycle

### Create / update (canonical write path)

All writes go through `assignment_bll`:

- `create_assignment()` — one row per role grant; syncs junction rows
- `update_assignment()` — mutates scope, mode, validity; re-syncs junction
- `revoke_assignment()` — sets `status=revoked`, records `revoked_by/at`

`membership_bll` delegates assignment writes to `assignment_bll`.

### Scope resolution rules

| Input | Result |
|-------|--------|
| `all_locations=True` | Tenant-wide; junction rows cleared |
| `branch_ids=[...]` | Scoped; junction rows synced to exact set |
| Single `branch_id` (API convenience) | Normalized to one junction row |

Helpers in `assignment_scope.py`:

- `assignment_covers_branch()` — junction + `all_locations` only
- `filter_assignments_in_scope()` — ORM entry point for branch/tenant-wide queries
- `collect_accessible_branch_ids()` — union of junction branch IDs; `None` when tenant-wide

## Revoke behavior

`DELETE /staff-assignments/{id}` soft-revokes (`status=revoked`).

**Only `ACTIVE` and `FUTURE` assignments participate in authorization.**

Revoked and expired assignments are excluded by `filter_assignments_for_authorization()`
before permission or branch-access resolution.

## Authorization flow

```
Request
  → tenant context resolution
  → permission_selector.get_user_permission_slugs()
      → active membership lookup
      → filter_assignments_for_authorization()   # ACTIVE/FUTURE only
      → filter_assignments_in_scope(branch_id)   # junction + all_locations
      → role IDs → permission slugs
  → rbac_bll.get_effective_permissions()
      → owner role slug (if tenant owner)
      → assignment role slugs (non-terminal only)
      → RolePermission lookup
```

Branch workspace access (`workspace_bll.user_can_access_branch`) uses the same
non-terminal filter and `membership_covers_branch()`.

## Production data maintenance

### consolidate_legacy_assignments

Management command for databases that still have duplicate non-terminal
assignments for the same `(membership, role)`. Merges duplicates into one row
with unioned junction locations. Idempotent; supports `--dry-run` and
`--tenant`.

Run before deploying migration `0012_remove_staffassignment_branch` if scoped
rows lack junction data.

## Migration history (access app)

| Migration | Purpose |
|-----------|---------|
| 0006 | Additive assignment fields (`all_locations`, `mode`, status, audit) |
| 0007 | `StaffAssignmentLocation` junction table |
| 0008 | Backfill junction from legacy `branch` column |
| 0009 | Drop per-branch uniqueness constraints |
| 0010 | Audit duplicate non-terminal grants (CI gate) |
| 0011 | `unique_non_terminal_membership_role_grant` |
| 0012 | Remove `StaffAssignment.branch` column |

Historical migrations are not rewritten. Migration `0012` audits that every
scoped assignment has at least one junction row before dropping `branch`.

## Indexes and constraints (final state)

**StaffAssignment**

- `unique_non_terminal_membership_role_grant` — one active/future grant per `(membership, role)`
- Index on `(membership, status)`, `(role)`

**StaffAssignmentLocation**

- `unique_assignment_branch_location` — one row per `(assignment, branch)`
- Index on `(branch)`

## What was removed in Wave 2

- `StaffAssignment.branch` mirror column
- Dual-read fallbacks in scope helpers and serializers
- Legacy per-branch assignment uniqueness
- `all_locations_implies_null_branch_mirror` check constraint
