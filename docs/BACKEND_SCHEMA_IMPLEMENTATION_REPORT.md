# Backend Schema Implementation Report — Phase Z.3, Step 2

Implements docs/BACKEND_SCHEMA.dbml against the audit in
docs/BACKEND_SCHEMA_ALIGNMENT_REPORT.md. Verified end-to-end against a real
Postgres 16 + Redis instance (Django 6.0.5, Python 3.12 venv).

## 1. Old architecture removed

- `accounts.User.role` (CharField, customer/admin) — deleted.
- `tenants.Owner` model and `Tenant.owner` FK (PROTECT) — deleted.
- `tenants/models/place.py` and its whole dead parallel API surface:
  `tenants/selectors/place_dal.py`, `tenants/services/place_bll.py`,
  `tenants/api/views/place.py`, `tenants/api/serializers/request/place_request.py`,
  `tenants/api/serializers/response/place_response.py`, plus a dead
  `tenants/admin/place.py` (double-registered `Tenant`/`WorkingHour` admin,
  never imported) — all deleted. Verified via import-graph grep before
  deleting: `tenants/api/views/__init__.py`, `tenants/services/__init__.py`,
  `tenants/selectors/__init__.py` only ever imported the `tenant.py`/`tenant_dal`/
  `tenant_bll` family.
- `access.StaffMembership` / `access.StaffAssignment` and the
  `TenantOwnerChecker` owner-bypass in `access/authorization/tenant_access.py`
  (`BaseTenantPermission.has_permission()` no longer short-circuits on
  ownership) — deleted.
- `Permission.slug` renamed to `Permission.code` everywhere (selectors,
  services, serializers, seed data).

## 2. New architecture

- `accounts.User`: `account_type` (customer/business) added. `is_active`/
  `is_staff`/`is_deleted`/`deleted_at`/`country_code` kept as explicitly
  documented backend-internal extensions (Django auth requires
  `is_active`/`is_staff`); the RBAC path never reads them.
- `tenants.Tenant`: `owner` FK removed, `business_types` (JSONField,
  default `[]`) and 5-value `status` enum added. **Deviation**: kept
  `tax_percentage`, `image`, `type`, `is_active` as extra columns beyond the
  schema's floor — `tenant_bll`/serializers depend on them heavily and the
  hard requirement (no `owner` FK, no `Owner` model) is satisfied regardless.
- `tenants.Branch`: `slug` uniqueness changed from global to
  `UniqueConstraint(tenant, slug)`; added `is_default`, `location`,
  `contact`, `business_hours` (JSON), `settings`. `status` enum changed to
  active/inactive/maintenance; a data migration (`tenants.0003`) converts
  any legacy `closed` rows to `inactive`. **Deviation**: `WorkingHour` table
  kept alongside the new `business_hours` JSON field rather than being
  dropped (lower risk; no automatic WorkingHour→JSON backfill migration was
  written since the repo has no existing WorkingHour rows) — new code
  should prefer `Branch.business_hours`.
- `access.TenantMembership` (replaces `StaffMembership`): `user`, `tenant`,
  `branch_scope` (all/selected, default selected), `status`
  (active/suspended/revoked, default active), unique per (user, tenant).
  **Deviation**: the old `pending` invite status has no target equivalent —
  invites now create a `TenantMembership` row directly with `status=active`.
- `access.TenantMembershipRole` (replaces the role half of
  `StaffAssignment`) — M:N, multiple roles per membership allowed.
- `access.TenantMembershipBranch` (new) — M:N, meaningful only when
  `branch_scope=selected`.
- `access.Role`/`Permission`/`RolePermission` — structurally unchanged
  besides `slug`→`code` on `Permission`.
- RBAC resolution is now exclusively
  `User -> TenantMembership -> tenant_membership_roles -> role_permissions -> Permission`
  (`access/selectors/permission_dal.py`, `access/authorization/tenant_access.py`).
  Ownership is expressed only by attaching the `owner` role to a membership.

## 3. Migrations created

- `accounts/migrations/0002_remove_user_role_user_account_type.py` — drops
  `role`, adds `account_type`.
- `tenants/migrations/0002_remove_owner_user_and_more.py` — drops `Owner`
  model and `Tenant.owner`; adds `business_types`/`is_active` on Tenant;
  adds `is_default`/`location`/`contact`/`business_hours`/`settings` on
  Branch; changes Branch slug uniqueness to `(tenant, slug)`; expands both
  status enums; renames `tenant`/`branch` tables to `tenants`/`branches`.
- `tenants/migrations/0003_migrate_closed_status.py` — data migration,
  converts any `Branch.status='closed'` rows to `'inactive'`.
- `access/migrations/0003_tenantmembership_tenantmembershipbranch_and_more.py`
  — creates `TenantMembership`, `TenantMembershipRole`,
  `TenantMembershipBranch`; renames `Permission.slug`→`code`; drops
  `StaffMembership`/`StaffAssignment`; renames `permission`/`role`/
  `rolepermission` tables to `permissions`/`roles`/`role_permissions`.
- `access/migrations/0004_seed_roles_permissions.py` — data migration,
  seeds the 8 roles and a baseline permission set (tenant/branch/staff/menu/
  orders × view/edit/manage, plus `tenant.delete`) generated from the
  `RequirePermission(...)` call sites already in the codebase. **Owner gets
  every permission as literal seeded rows** — proven by test
  `OwnerNoBypassTests.test_owner_access_requires_seeded_permissions`, which
  deletes the owner role's `RolePermission` rows and shows access is lost.
- `access/migrations/0005_rename_..._and_more.py` — renames two index names
  that exceeded a 30-char backend limit.

**Deviation from the requested 7-step sequence**: since this is a fresh
repo with zero existing `Owner`/`StaffMembership`/`StaffAssignment` rows
(confirmed empty tables pre-migration), the additive-schema-change and
old-model-removal steps were generated together per app by Django's
autodetector rather than split into separate "additive" and "final removal"
migrations. There is no backfill migration for existing Owner→membership or
StaffAssignment→role/branch data because there was no data to backfill;
the migration graph is structurally correct for a populated DB run before
this branch (data existing under the old schema would need the DB
reset/backfilled manually — flagged as a risk if this branch is ever
deployed onto a non-empty production DB).

## 4. API changes

- `GET /api/auth/me/` — reshaped to
  `{ user: {id, email, accountType}, memberships: [{tenantId, tenantSlug, roles, branchAccess}], activeMembership }`.
  `branchAccess` is `{scope: "all"}` or `{scope: "selected", branchIds: [...]}`.
  **Deviation**: no session/current-tenant concept exists anywhere in this
  codebase (checked `core/middleware`, `access/authorization`) — `activeMembership`
  defaults to the first active membership by `created_at`.
- `GET /api/tenants/` — restricted to `is_staff` users only (returns empty
  queryset otherwise); an unscoped "list every tenant" endpoint for regular
  users is a tenant-isolation bug.
- `GET /api/tenants/me/` (new) — returns only tenants where the caller has
  an active `TenantMembership`, shape `[{id, name, slug, roles}]`.
- `GET /api/tenants/<tenant_id>/branches/` — now 403s unless the caller has
  an active membership in that tenant, then filters by `branch_scope` (all
  branches vs. only `tenant_membership_branches`-listed ones).
- `access` app: `staff-memberships`/`staff-assignments` endpoints replaced
  by `tenants/<tenant_id>/memberships/` (CRUD) plus
  `memberships/<id>/roles/` and `memberships/<id>/branches/` (POST/DELETE)
  for attaching/detaching roles and branches. `RolePermissionAddView` now
  takes `permission_codes` instead of `permission_slugs`.

## 5. Tests added (`access/tests/test_schema_alignment.py`, 12 tests, all passing)

- `AuthMeTests`: `/auth/me/` shape (all-scope and selected-scope
  `branchAccess`), 401 when unauthenticated.
- `TenantIsolationTests`: user A cannot see user B's tenants via
  `/api/tenants/me/`; revoked memberships are excluded.
- `BranchScopingTests`: selected-scope membership only sees assigned
  branches; all-scope sees every branch; 403 without membership.
- `OwnerNoBypassTests`: owner access requires seeded `RolePermission` rows
  (deleting them removes access — proves no code bypass); asserts
  `TenantOwnerChecker` no longer exists.
- `NoUserRoleReferenceTests`: repo-wide grep for `user.role`/`User.role`
  finds nothing outside migrations/tests; `User` model has no `role` field.

## 6. Verification performed

- `python manage.py check` — clean.
- `python manage.py makemigrations --check --dry-run` — no changes
  detected (migrations are complete).
- `python manage.py migrate --plan` / `python manage.py migrate` — applied
  cleanly against a real Postgres 16 database (all migrations including
  `menu`/`orders`/`token_blacklist` etc.), no errors.
- `python manage.py test` — 12/12 passing (this is the only test suite in
  the repo; no pre-existing tests were found to regress).

## 7. Remaining risks / deviations requiring human review

1. Extra Tenant/Branch columns kept beyond the schema floor
   (`tax_percentage`, `image`, `type`, `is_active` on Tenant; `phone`,
   `address`, `city`, `latitude`, `longitude`, `is_active` on Branch).
2. `WorkingHour` table kept alongside `Branch.business_hours` JSON — no
   backfill between them was written (no existing rows to migrate).
3. `pending` membership invite status has no equivalent — invites are
   created as `status=active` immediately; there is no invite-acceptance
   flow modeled.
4. `activeMembership` in `/auth/me/` is a client-side-free default (first
   active membership by creation order) — there is no persisted
   "current tenant" concept anywhere in this codebase.
5. Migrations were generated as consolidated per-app changes rather than
   the fully staged 7-step sequence, since the repo had zero rows in any of
   the tables being restructured; this is documented above in §3.
6. `tenant_bll.create_tenant` now auto-creates a `TenantMembership` with the
   `owner` role for the creating user (replacing the old `Owner.get_or_create`
   flow) — this is new business logic, not explicitly speced beyond "ownership
   is a membership + owner role", worth a second look.
