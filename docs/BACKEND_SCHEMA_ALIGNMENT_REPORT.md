# Backend Schema Alignment Report — Phase Z.3, Step 1

Audit of the existing `back_samoon` Django backend against `docs/BACKEND_SCHEMA.dbml`
(the frozen target schema). Read-only audit — no code changed.

## 1. Existing Django apps

`SmartRestaurant` (project), `core`, `accounts`, `tenants`, `access`, `menu`, `orders`.

## 2. Existing models (by app)

- `accounts`: `User` (custom auth user), `OTPCode`
- `tenants`: **two parallel, conflicting model files**:
  - `tenants/models/tenant.py` → `Owner`, `Tenant`, `Branch`, `WorkingHour` (`TenantStatus`, `TenantType`, `BranchStatus`) — **this is the file actually imported** by `tenants/models/__init__.py`.
  - `tenants/models/place.py` → a second, unused/dead `Tenant`, `WorkingHour` definition (no `Branch`), with `Tenant.owner` as a direct FK to the user model instead of via an `Owner` entity. Not imported anywhere; only migration state matters, and no migration references `place.py` directly (Django migrations key off app label + model name, and both define a model literally named `Tenant`, so this is a latent collision risk, not just dead code).
- `access`: `Role`, `Permission`, `RolePermission`, `StaffMembership`, `StaffAssignment`
- `menu`: `Category`, `Item` (out of scope for this phase)
- `orders`: `Order`-related models (out of scope for this phase)

## 3. Existing User model

`accounts/models/user.py`:
- `AbstractBaseUser` + `PermissionsMixin`, `db_table = "users"`, UUID pk.
- Fields: `country_code`, `phone_number` (unique), `email` (unique), `first_name`, `last_name`, `avatar` (ImageField), **`role` (CharField, choices `customer`/`admin`)**, `is_verified`, `is_active`, `is_staff`, `is_deleted`, `deleted_at`, `created_at`, `updated_at`.
- `USERNAME_FIELD = "phone_number"`.

## 4. Existing Tenant/Branch models

Active (`tenant.py`):
- `Owner` — separate entity, `OneToOneField` to `User`, PROTECT. Not in target schema at all.
- `Tenant` — `owner` FK to `Owner` (PROTECT), `name`, `slug`, `tax_percentage`, `image`, `type` (coffee/restaurant), `status` (active/inactive/closed — 3 values), `settings` (JSON), timestamps. Unique constraint `(owner, name)`.
- `Branch` — `tenant` FK (CASCADE), `name`, **global-unique** `slug` (not tenant-scoped), `phone`, `address`, `city`, `latitude`, `longitude`, `status` (active/inactive/closed), `is_active`, timestamps.
- `WorkingHour` — per-branch, separate table (not embedded JSON).

## 5. Existing authentication implementation

`accounts/services/auth_service.py` + `otp_bll.py`/`verification.py` — phone/email OTP-based auth, consistent with `users.phone_number`/`email` being nullable+unique in the target schema. No structural conflict expected here, not audited line-by-line (out of scope for schema alignment).

## 6. Existing RBAC implementation

- `Role` (`access/models/role.py`) — UUID pk, `slug` (choices: owner/admin/manager/cashier/waiter/kitchen/marketing/support — matches target seed list), `name`, `description`, `system_role`. Close to target `roles` table; missing nothing structurally except the enum-vs-seeded-row difference (already a plain table here, good).
- `Permission` — UUID pk, `resource`, `action`, `slug` (unique), `description`. Roughly equivalent to target `permissions` (code vs slug naming difference only).
- `RolePermission` — plain M:N join, matches target `role_permissions` structurally.
- `StaffMembership` — plays the role of `tenant_memberships` but shaped very differently: `tenant` FK, `user` FK, `status` (pending/active/suspended/removed), `invited_by`, `joined_at`. **No `branch_scope` field.**
- `StaffAssignment` — plays the role of *both* `tenant_membership_roles` and `tenant_membership_branches` combined: one row = `(membership, role, branch|null)`, unique per `(membership, branch)`, plus a unique constraint enforcing at most one *tenant-wide* (`branch IS NULL`) assignment per membership. This is a fundamentally different shape than the target's `branch_scope` enum + separate branch-assignment join table.
- `TenantOwnerChecker` (`access/authorization/tenant_access.py`) — **hardcoded owner bypass**: `is_owner()` checks `Tenant.objects.filter(id=tenant_id, owner__user_id=user.id)` and `BaseTenantPermission.has_permission()` grants access unconditionally if `is_owner()` is true, *before* ever consulting `RolePermission`. This directly violates the target schema's §6 rule ("NO runtime owner bypass — owner access must come only from seeded RolePermission rows"). `StaffAssignment.clean()` even actively forbids assigning the `owner` role to any `StaffAssignment`, reinforcing that ownership is currently a side-channel via the `Owner`/`Tenant.owner` relation, not RBAC.

## 7. Existing migrations

- `accounts/0001_initial.py` — creates `User`, `OTPCode`.
- `tenants/0001_initial.py` — creates `Owner`, `Tenant`, `Branch`, `WorkingHour` (from `tenant.py`).
- `access/0001_initial.py` + `0002_initial.py` — creates `Role`, `Permission`, `RolePermission`, `StaffMembership`, `StaffAssignment` and their FKs/constraints.
- No production data assumed present (fresh `Initial commit` on `main`, single branch) — dropping/recreating tables is technically possible, but the task instructs not to delete migrations or drop tables, so this report treats the schema as if it must be migrated forward safely regardless.

## 8. Conflicts with `BACKEND_SCHEMA.dbml`

| Target table | Existing equivalent | Conflict |
|---|---|---|
| `users` | `accounts.User` | Has a `role` field (must be removed — target explicitly forbids any role/permission/tenant column on User). No `account_type` field (target requires `customer`/`business` enum). Missing `avatar` as target expects (has it, but as ImageField not varchar — acceptable, minor). Extra fields not in target (`country_code`, `is_active`, `is_staff`, `is_deleted`, `deleted_at`) — Django auth framework requires some of these (`is_active`, `is_staff` are `PermissionsMixin`/admin requirements); not literal violations but need explicit decision on whether to keep. |
| `tenants` | `tenants.Tenant` (`tenant.py`) | Has `owner` FK (target: no owner column, ownership only via membership+role). `status` enum has 3 values (`active/inactive/closed`) vs target's 5 (`active/trial/suspended/churned/archived`). No `business_types` field. Has `tax_percentage`, `image`, `type` fields not in target (need a decision: keep as extra columns, or these belong on Branch/elsewhere per target's `settings`/`location` JSON). |
| `branches` | `tenants.Branch` | `slug` is **globally unique**, not `(tenant_id, slug)`-scoped as target requires — **direct constraint conflict**. `status` enum is `active/inactive/closed` vs target's `active/inactive/maintenance`. No `is_default`, no `location`/`contact`/`business_hours` JSON fields (currently normalized into flat columns + separate `WorkingHour` table). |
| `tenant_memberships` | `access.StaffMembership` | No `branch_scope` field at all — **structural gap**, this is the core new concept the whole membership model depends on. `status` enum differs (`pending/active/suspended/removed` vs target's `active/suspended/revoked`; also target has no `pending` state — needs a decision on invite-flow modeling). |
| `tenant_membership_roles` | `access.StaffAssignment` (partial) | `StaffAssignment` conflates role assignment *and* branch assignment into one row, and encodes "tenant-wide" as `branch IS NULL` rather than a `branch_scope` flag on the membership. Also enforces only **one role per branch per membership** (unique `(membership, branch)`), whereas target's `tenant_membership_roles` allows a membership to hold **multiple roles simultaneously** (e.g., cashier + waiter) with permissions resolved as a union — **behavioral conflict**, not just structural. |
| `tenant_membership_branches` | *(none)* | Doesn't exist as a distinct concept — currently folded into `StaffAssignment.branch`. Needs to be introduced as its own join table once `branch_scope=selected` is modeled properly. |
| owner bypass | `TenantOwnerChecker` / `BaseTenantPermission` | **Direct rule violation**: hardcoded `if is_owner(): return True` bypass in `access/authorization/tenant_access.py`, contradicting target's "no runtime owner bypass" rule. Must be replaced by seeding the `owner` role with every permission via `RolePermission`, and removing the bypass entirely. |
| `Owner` model | `tenants.Owner` | Not present in target schema at all — target says ownership is expressed *exclusively* via a `tenant_memberships` row with the `owner` role. This whole model/table needs to be retired, and its data (if any) migrated into `tenant_memberships` + `tenant_membership_roles`. |
| duplicate `Tenant`/`WorkingHour` defs | `tenants/models/place.py` | Dead code defining second `Tenant`/`WorkingHour` models with a different (direct owner-FK) shape. Should be deleted — never wired into `__init__.py`, no migration depends on it, but it is confusing and a landmine for whoever edits `tenants/models/__init__.py` next. |

## 9. Migration risks

- **Removing `User.role`**: if any application code (serializers, permission checks, admin) currently branches on `user.role`, that logic must be re-pointed at the membership/role resolution path before the column can be dropped — audit all read sites before dropping.
- **`Owner` model retirement**: `Tenant.owner` is `on_delete=PROTECT` and has a `unique_together (owner, name)` constraint — removing it requires a data migration step (backfill an `owner`-role `tenant_memberships` row for every existing `Owner`↔`Tenant` pair) *before* the column/table can be dropped, not a simple rename.
- **`Branch.slug` global-unique → tenant-scoped unique**: dropping the global uniqueness and adding `(tenant_id, slug)` composite uniqueness is safe additively, but any code currently doing lookups by bare `slug` (e.g., subdomain routing) must be updated to filter by `tenant_id` too, or duplicate slugs across tenants will break those lookups.
- **`StaffAssignment` → `tenant_membership_roles` + `tenant_membership_branches` split**: this is the highest-risk migration — it's a genuine reshape (one row currently encodes role+branch together; target wants role and branch-scope decoupled). Existing `StaffAssignment` rows must be replayed into: (a) set `tenant_memberships.branch_scope` based on whether the membership has any non-null-branch assignments vs a null-branch (tenant-wide) one, (b) populate `tenant_membership_roles` (role, deduplicated per membership), (c) populate `tenant_membership_branches` for `selected`-scope memberships. This needs explicit design/approval, not a mechanical migration.
- **Removing the owner-bypass permission check**: functionally security-sensitive — until `RolePermission` is fully seeded for `owner`, removing `TenantOwnerChecker`'s bypass would lock out real owners. Must be sequenced: seed owner permissions first, verify, *then* remove the bypass.
- **Deleting `tenants/models/place.py`**: safe (dead code, unreferenced), but confirm no migration or import path references it before deleting.
- **Enum value changes** (`tenant_status`, `branch_status`): adding new choices is additive/safe; no existing rows use the new values yet since this is a fresh schema, so no data-loss risk currently, but downstream code (serializers, frontend contracts) consuming these choices needs updating in lockstep.

## 10. Required changes (summary, pending approval)

1. `accounts.User`: drop `role` field; add `account_type` enum field; decide disposition of `country_code`/`is_active`/`is_staff`/`is_deleted`/`deleted_at` (keep as backend-internal extensions vs. remove).
2. `tenants`: delete dead `place.py` duplicate models. Remove `Owner` model and `Tenant.owner` FK (migrate ownership into membership+role). Expand `tenant_status` to 5 values. Add `business_types` JSON field to `Tenant`.
3. `branches`: change `slug` uniqueness from global to `(tenant_id, slug)`. Add `is_default`, `location`, `contact`, `business_hours` JSON fields (or confirm normalized-column approach is an acceptable equivalent — **needs explicit decision**, since target models these as JSON not normalized columns). Expand `branch_status` to include `maintenance`.
4. `access`: rename/reshape `StaffMembership` → `tenant_memberships`, adding `branch_scope`; reshape `status` choices to `active/suspended/revoked` (drop `pending`, or confirm how invite-pending state should be represented under the frozen schema — **needs explicit decision**). Split `StaffAssignment` into `tenant_membership_roles` (M:N, multi-role support) + new `tenant_membership_branches` (M:N) tables. Seed all permissions onto the `owner` role via `RolePermission`. Remove the `TenantOwnerChecker` bypass in `access/authorization/tenant_access.py` once owner permissions are seeded and verified.

### STOP — approval required

Items 2–4 above involve destructive/structural migrations (dropping `Owner`, reshaping `StaffAssignment`, removing the owner bypass, changing `Branch.slug` uniqueness) and touch data modeling decisions not fully specified by the schema alone (branch JSON vs normalized columns, disposition of the `pending` membership state, disposition of `User` fields outside the target list). Per Step 1 instructions, **implementation stops here pending your approval** of the migration strategy in section 9–10 above before Step 2 (model implementation) begins.
