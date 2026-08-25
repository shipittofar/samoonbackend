# Backend Contract Verification Report — Phase Z.4

Verification and hardening pass over the Phase Z.3 schema alignment
(commit `72563d4`). No new features, CRUD modules, or schema redesign were
performed — this phase verifies, tests, and hardens what Z.3 already built.

Verified against a real Postgres 16 + Redis instance (Django 6.0.5, Python
3.12, `/tmp/venv`), reusing the environment set up during Z.3.

## 1. Verified contracts

### `GET /api/auth/me/` — PASS (no shape bug found)
`accounts/api/views/auth.py::MeView` builds the response as a plain dict
(not a DRF serializer), so there is no snake_case-default risk. Verified:
exact camelCase field names (`tenantId`, `tenantSlug`, `accountType`,
`branchAccess`, `branchIds`); `all` scope omits `branchIds`; `selected`
scope includes it; zero-membership user gets `"memberships": []` and
`"activeMembership": null`; multi-tenant user gets one entry per tenant;
multi-role membership lists every role. All covered by new tests in
`AuthMeEdgeCaseTests`.

### `GET /api/tenants/me/` — PASS
`tenants/api/views/tenant.py::MyTenantListAPIView` filters strictly on
`TenantMembership.objects.filter(user=request.user, status="active")`.
Verified suspended and revoked memberships are both excluded (new test
`TenantIsolationSuspendedRevokedTests`), and cross-user leakage is
prevented (pre-existing `TenantIsolationTests`).

### `GET /api/tenants/<tenant_id>/branches/` — PASS
`BranchListAPIView.get_queryset` requires an active membership in the
path's `tenant_id` or raises DRF `PermissionDenied` (403). Verified `all`
scope returns every branch, `selected` scope returns only
`tenant_membership_branches`-listed ones, and a user cannot see another
tenant's branches by guessing its id (new
`BranchIsolationCrossTenantTests`).

**403 vs 404 decision**: kept as 403. The rest of this codebase's
tenant/branch ownership checks (`TenantPermissionDeniedException`,
`BranchPermissionDeniedException` in `core/exceptions/tenant.py`, and
`access/authorization/tenant_access.py`'s `PermissionDeniedException`) all
use 403 for "authenticated but not permitted," reserving 404 for
"object genuinely does not exist." Switching this one endpoint to 404
would be inconsistent with the rest of the API's exception conventions, so
it was left as-is rather than "fixed."

## 2. Security findings (item 7)

Grepped all apps for `.objects.get(id=`, `.objects.get(pk=` on
client-suppliable ids, plus manual review of every tenant/branch id-taking
view.

| Location | Verdict | Notes |
|---|---|---|
| `access/services/membership_bll.py:118` `TenantMembership.objects.get(id=membership_id, tenant_id=tenant_id)` | SAFE | Always scoped by `tenant_id` from the URL; view above it (`TenantMembershipRetrieveUpdateView`) is gated by `RequirePermission("staff.manage")`, which routes through `permission_dal`. |
| `access/services/membership_bll.py:124`, `access/services/role_bll.py:55` `Role.objects.get(id=role_id)` | SAFE | Roles are a global reference table, not tenant-scoped data; no cross-tenant leak possible. |
| `access/selectors/permission_dal.py:31` `TenantMembership.objects.get(id=membership_id)` | SAFE | Internal helper only ever called with a `membership_id` already resolved from a tenant-scoped query. |
| `core/middleware/websocket_auth.py:18` `User.objects.get(id=validated_token["user_id"])` | SAFE | `user_id` comes from a verified JWT, not client-supplied request data. |
| `tenants/api/views/tenant.py` `TenantRetrieveAPIView` / `BranchRetrieveAPIView` | **DOCUMENTED, NOT CHANGED** | `tenant_bll.get_tenant()` / `branch_bll.get_branch()` have no membership/permission check at all, and neither view sets `permission_classes`, so with no project-wide `DEFAULT_PERMISSION_CLASSES` configured these are fully `AllowAny` — any unauthenticated caller can read any tenant's or branch's full record (including `tax_percentage`, `settings`, address/contact fields) by id. This *may* be intentional (a public storefront needs to read tenant/branch info to let customers browse/order without being a staff member), which is a plausible reading of this being a restaurant-ordering backend. Locking it down to membership-only would be a behavior change with real risk of breaking the customer-facing ordering flow, which is outside this phase's mandate ("fix genuine security bugs," not "redesign public read access"). **Flagged for explicit human sign-off**: confirm whether tenant/branch retrieve is meant to be public, and if not, add an `IsAuthenticated` + read-permission check in a follow-up phase. |
| **`orders/services/orders_bll.py:171`** `order.tenant.owner_id != user.id` | **VULNERABLE / BROKEN — FIXED** | `Tenant.owner` was removed in Z.3, and `Order` has no `tenant` field at all (only `Order.branch`, tenant is reachable via `branch.tenant`) — this line would raise `AttributeError` on every call to `update_order_status`, meaning the "owner-only" status-update endpoint was completely broken (100% failure) and simultaneously still coded against the deleted ownership model. Fixed to resolve tenant via `order.branch.tenant_id` and check `permission_selector.user_has_permissions(..., permission_codes=["orders.edit"])`, which is the seeded permission already granted to `owner`, `manager`, `cashier`, `waiter`, and `kitchen` roles — i.e. it now actually routes through the RBAC path instead of a dead ownership shortcut. |

**Separately discovered, out of scope for this phase**: `orders/selectors/orders_dal.py::get_order_by_public_id_for_update` filters on `Order.objects... .filter(public_id=public_id)` and `.select_related("tenant", "customer")`, but `Order` has neither a `public_id` field nor a `tenant` field (only `id` (UUID pk) and `branch`). This means `cancel_order` and `update_order_status` are broken independent of the fix above — this is a pre-existing bug in the `orders` app that predates and is unrelated to the Z.3 schema-alignment work (the `orders` app wasn't touched by Z.3), so a full fix is out of scope here per the "no new CRUD/feature work" constraint. Flagged for a dedicated orders-app bugfix pass.

## 3. Permission-resolution audit (item 4)

Repo-wide grep for `user.role`/`User.role`, `tenant.owner`/`Tenant.owner`,
`Owner` model usage, `is_owner` shortcuts, and `is_staff`-as-RBAC-bypass,
excluding migrations and tests:

- `orders/services/orders_bll.py:171` `order.tenant.owner_id` — **fixed**, see §2.
- `core/exceptions/orders.py:79` `code = "not_tenant_owner"` — just an error code string, not a bypass; left as-is (renaming would be cosmetic and risk breaking API consumers matching on the code).
- `tenants/services/tenant_bll.py:22-41` `_is_tenant_owner` / `_assert_owns_tenant` / `_assert_owns_branch` — **reviewed, acceptable**: this resolves ownership via `TenantMembership.objects.filter(..., tenant_membership_roles__role__slug="owner")`, i.e. it still goes through the real `TenantMembership -> role` path, just as a direct query instead of calling into `permission_dal`. It is not a `User`-field or `Tenant.owner`-FK bypass — the same conceptual check as `permission_dal.user_has_permissions(..., ["some.permission"])` would provide, but keyed on a role slug rather than a permission code. Recommend (not applied, would be a design change beyond hardening) unifying this with `permission_dal` by adding a real seeded permission-based check (e.g. `tenant.manage`) instead of a hardcoded `role__slug="owner"` string, so ownership isn't special-cased outside the RBAC table — noted as a follow-up, not fixed now since `Tenant`/`Branch` create/update/delete aren't in the Z.3 endpoint list and changing their authorization model is a judgment call beyond "fix a contract-shape bug."
- `tenants/api/views/tenant.py:92` `if not self.request.user.is_staff` — **acceptable**: this is `TenantListAPIView`, an explicitly staff-only "list every tenant" endpoint (platform-admin use), not a per-user RBAC-gated endpoint. It doesn't bypass `permission_dal`, it correctly restricts a naturally global endpoint to Django `is_staff`. Left as-is.
- No occurrences of `Owner` model usage remain (model itself was deleted in Z.3; grep confirms no import/reference anywhere).
- No `if request.user.is_staff: return True` used as a stand-in for a membership-scoped RBAC check anywhere in `access`, `tenants`, `menu`, `orders`, or `core`. Django admin's own `is_staff` gate on `/admin/` was not touched (expected, framework behavior).

## 4. Migration review (item 5)

- `python manage.py makemigrations --check --dry-run` → **no changes
  detected** (verified against live Postgres 16).
- `python manage.py check` → clean, no issues.
- DB-level `UniqueConstraint(user, tenant)` on `TenantMembership`: present
  (`access/migrations/0003...py`, confirmed against `uq_tenant_memberships_user_tenant`
  in the DBML).
- DB-level `UniqueConstraint(tenant, slug)` on `Branch`: present
  (`tenants/migrations/0002...py`).
- FK `on_delete=CASCADE` for `branches.tenant_id`,
  `tenant_memberships.user_id`/`tenant_id`,
  `tenant_membership_branches.*`, `tenant_membership_roles.*`,
  `role_permissions.*`: all confirmed `CASCADE` in the migration files,
  matching the DBML's `delete: cascade` annotations.
- Indexes: `ix_tenant_memberships_user_status`,
  `ix_tenant_memberships_tenant_status`, `ix_branches_tenant_status` all
  present (the latter two renamed in `0005_rename_...py` to fit a 30-char
  backend limit, as documented in the Z.3 report — functionally
  equivalent). Uniques on `users.email`, `users.phone_number`,
  `tenants.slug`, `roles.slug`, `permissions.code` all present.
- Reversibility: `tenants/migrations/0003_migrate_closed_status.py` and
  `access/migrations/0004_seed_roles_permissions.py` are data migrations.
  Neither has an explicit `reverse_code`; both currently reverse as
  `RunPython.noop`-equivalent (irreversible in effect but not destructive —
  reversing them just leaves seeded/converted rows in place). This is
  acceptable per the task's own criterion ("`RunPython.noop` is acceptable
  for straightforward reversible-in-effect migrations, just don't leave
  silently-irreversible destructive migrations undocumented") — neither
  migration deletes data, so no fix was made. No genuinely missing
  constraint or index was found, so no new migration was added.

## 5. Remaining decisions requiring human sign-off (item 6 — documented only, not implemented)

**A) Extra Tenant/Branch columns beyond the schema floor**
(`Tenant.tax_percentage/image/type/is_active`;
`Branch.phone/address/city/latitude/longitude/is_active`).
**Recommendation: KEEP.** All of them are actively read/written by
`tenant_bll`/`branch_bll` and their serializers (confirmed in
`tenant_bll.update_tenant`/`update_branch`), so removing them would break
existing, live API consumers. The frozen DBML defines a schema floor, not
a ceiling — extra columns don't violate any explicit rule in
`BACKEND_SCHEMA.dbml`. No action needed.

**B) `WorkingHour` table vs `Branch.business_hours` JSON**
**Recommendation: keep both, as-is, for now** — but flag it for
consolidation in a future phase. The two representations are currently
unsynchronized (no code path keeps them consistent with each other), which
is worse than either "normalized-only" or "JSON-only" alone: a consumer
reading `business_hours` and a consumer reading `WorkingHour` rows could
disagree. Since this phase is verification-only and there is no evidence
of production data in either representation yet (per the Z.3 report, the
repo had zero existing rows), the least-risk move now is documentation;
picking one representation and migrating is a schema decision for a human,
not something to guess at here.

**C) Invite/pending state**
**Recommendation: Option 1 (keep active-only membership creation, no
pending concept) for now.** The frozen `membership_status` enum in
`BACKEND_SCHEMA.dbml` has exactly `active`/`suspended`/`revoked` — no
`pending` value. Option 2 (a real invitation flow) is achievable without
violating the frozen schema, but it would require a **new, separate**
model (e.g. `TenantInvitation`) rather than overloading
`TenantMembership.status`, since the enum has no room for `pending`. That
is new-model territory, explicitly out of scope for Z.4 ("You may NOT
invent new endpoints or new models"). Recommend scoping a dedicated
invitation-model phase if/when product requirements call for
delayed-acceptance invites.

**D) `activeMembership` resolution rule**
Current rule: first active membership by `created_at`. **Recommendation:**
add an explicit `?tenant=<slug>` query param (or `X-Tenant-Slug` header) on
`GET /api/auth/me/` that the frontend can pass when it already knows which
tenant context it's in (e.g. from the URL/subdomain), falling back to
"first active membership by `created_at`" when absent. This requires no
new persisted state and is backward compatible. The DBML's `tenants.slug`
note about "future subdomain routing" suggests subdomain-based resolution
is the eventual target, but that depends on infra (subdomain routing/DNS)
that doesn't exist yet; a request-time hint is the lowest-risk stepping
stone. A "most-recently-active membership" or persisted "current tenant"
selection would require new session/cookie/DB state (this repo currently
has none — confirmed via `core/middleware`), which is real new-state
territory belonging to a future phase, not Z.4. No code changes were made
for this item; it remains "first active membership by `created_at`."

## 6. Tests added and run

Extended `access/tests/test_schema_alignment.py` (12 → 21 tests, all
passing against live Postgres 16):

- `AuthMeEdgeCaseTests` (4 tests): zero-membership → `[]`/`null`,
  multi-tenant scoping, multi-role membership, `all`-scope omits
  `branchIds`.
- `TenantIsolationSuspendedRevokedTests` (1 test): both suspended and
  revoked memberships excluded from `/tenants/me/` in the same test.
- `BranchIsolationCrossTenantTests` (2 tests): cross-tenant branch
  guessing blocked (403); within-tenant `selected`-scope isolation.
- `PermissionResolutionTests` (2 tests): no-role membership has zero
  permissions; a role (`waiter`) grants exactly its seeded
  `RolePermission` codes.
- Pre-existing `OwnerNoBypassTests` (owner access requires seeded
  `RolePermission` rows, no code bypass) verified still present and
  passing, unmodified.

**Real run results** (Postgres 16 + Redis, same venv Z.3 used):
- `python manage.py test` → **21/21 passing**.
- `python manage.py makemigrations --check --dry-run` → no changes.
- `python manage.py check` → clean.

No tests were added for the `orders_bll.update_order_status` fix itself,
because exercising it end-to-end requires order/menu fixtures the `orders`
app has no existing test scaffolding for, and — as noted in §2 — the
`orders_dal` query it depends on (`get_order_by_public_id_for_update`) is
independently broken (references nonexistent `Order.public_id`/`Order.tenant`
fields) and would need a separate fix before any such test could pass
end-to-end. The permission-routing fix was verified by code
inspection only (confirmed `Order.branch`, `Branch.tenant_id`, and the
`orders.edit` permission code all exist and resolve correctly); this is
called out honestly rather than claimed as tested.

## 7. Recommended next phase

A dedicated `orders` app bugfix pass to repair
`orders_dal.get_order_by_public_id_for_update` (nonexistent `public_id`/
`tenant` field references) and add order-flow test coverage, since that
code path currently cannot function at all regardless of the
permission fix made here.
