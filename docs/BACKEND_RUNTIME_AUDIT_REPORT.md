# Backend Runtime Audit Report — Phase Z.5

Runtime audit and bugfix pass, building on Z.3 (`72563d4`, schema
alignment) and Z.4 (`203c771`, contract verification). This phase traced
live request paths (auth, authorization, tenant/branch isolation,
contract shapes, service layers) rather than re-reading static code, and
fixed everything genuinely broken that it found. No schema redesign, no
new endpoints/models. Verified against a real Postgres 16 + Redis
instance (`/tmp/venv`, DB `backsamoon`), reusing the environment from
Z.3/Z.4.

## 1. Files changed

- `orders/models/orders.py` — read only, confirmed real field set
  (`Order.branch`, `Order.id`, `Order.tax`, `Order.total`; no
  `public_id`/`tenant`/`tax_amount`/`total_amount`).
- `orders/selectors/orders_dal.py` — rewritten to use real fields;
  fixed `Address` FK creation; fixed `select_for_update()` outer-join bug.
- `orders/services/orders_bll.py` — rewritten to use `branch_id` instead
  of `tenant_id`, `order.id` instead of `public_id`, `tax`/`total`
  instead of nonexistent `tax_amount`/`total_amount`; added
  `order_number` generation; fixed delivery-address create/detach flow;
  fixed `OrderItem` creation (was missing required `name`/`total_price`).
- `orders/api/serializers/request/orders.py` — `tenant_id` → `branch_id`
  (UUID) for create/update; `table_number` corrected to `IntegerField`
  (model field is `PositiveIntegerField`, was `CharField`); discount
  validation's `tenant_id` fixed to `UUIDField` (Tenant's PK is UUID, was
  `IntegerField`, which would reject every real tenant id).
- `orders/api/serializers/response/orders.py` — response now derives
  `branch_id`/`branch_name`/`tenant_id`/`tenant_name` via `order.branch`
  (there is no `order.tenant`); added missing `total`/`service_charge`/
  `order_number` fields; fixed `tenant_id` type to `UUIDField`.
- `orders/api/urls.py`, `orders/api/views/orders.py`,
  `orders/ws/notifications.py` — `public_id` → `id` throughout (the
  field never existed on `Order`).
- `menu/api/urls.py` — every URL capture group renamed `place_id` →
  `tenant_id` (see bug #2 below).
- `menu/api/views/category.py`, `menu/api/views/item.py` — added
  `permission_classes` (RBAC, via `TenantMembership`/`permission_dal`) to
  every view; added `menu.view`/`menu.edit` gating.
- `menu/api/serializers/request/category.py`,
  `menu/api/serializers/request/item.py` — `tenant_id` fixed to
  `UUIDField` (was `IntegerField`; `Tenant.id` is a UUID PK).
- `access/authorization/tenant_access.py` — fixed a `TypeError` in the
  shared `RequirePermission` denial path (see bug #4 below) — this is
  the authorization primitive Z.4's `access/api/views/memberships.py`
  already depends on.
- `access/tests/test_schema_alignment.py` — added
  `AuthTokenValidityTests` (garbage/missing/tampered token → 401).
- `orders/tests/test_orders_runtime.py` (new) — 8 tests covering order
  creation against real model fields, RBAC-gated status update
  (no-permission denied, owner allowed, cross-tenant denied,
  `branch_scope=selected` denied/allowed), and customer order isolation.
- `menu/tests/test_menu_runtime.py` (new) — 7 tests covering
  unauthenticated/unauthorized denial and cross-tenant isolation for
  menu categories/items.

## 2. Bugs found and fixed

### Bug 1 — Orders app was completely non-functional (HIGHEST PRIORITY, as requested)
Every DAL/BLL method in `orders` referenced fields that don't exist on
`Order`: `.tenant` (real field is `.branch`, tenant reachable via
`branch.tenant`), `.public_id` (real PK is `.id`, a UUID), and
`tax_amount`/`total_amount` (real fields are `.tax`/`.total`). This meant
**every** orders endpoint — create, list, detail, update, cancel, and
status-update — would raise `AttributeError`/`FieldError` on first real
use. In addition:
- `Address` creation passed `order=order` to `Address.objects.create()`,
  but `Address` has no `order` field (the FK direction is
  `Order.delivery_address → Address`, not the reverse) — this alone
  would raise `TypeError` on every delivery order.
- `OrderItem` creation omitted the required `name`/`total_price` fields.
- `get_order_by_id_for_update`'s `select_for_update()` combined with
  `select_related("customer")` — `customer` is a nullable FK (guest
  checkout) — which Postgres rejects outright: *"FOR UPDATE cannot be
  applied to the nullable side of an outer join"*. This was caught live
  by the new test suite (500 on every status-update/cancel/edit call)
  and fixed by dropping `customer` from that specific `select_related`.
- `orders_bll.update_order_status`'s RBAC fix from Z.4 (`orders.edit`
  via `permission_dal`) is preserved and now actually reachable, since
  the query it depends on is fixed.

All of the above are fixed. **Verified end-to-end** (not just by code
inspection, unlike Z.4's honest disclaimer) via 8 new tests in
`orders/tests/test_orders_runtime.py`, all passing against live Postgres.

### Bug 2 — Menu app: URL/view kwarg name mismatch (100% failure)
Every non-create menu view (`MenuCategoryListView`/`DetailView`/
`UpdateView`/`DeleteView`, `MenuItemListView`/`DetailView`/`UpdateView`/
`DeleteView`, `ExtraListView`/`DetailView`/`UpdateView`/`DeleteView`,
`MenuItemExtraListView`/`CreateView`/`UpdateView`/`DeleteView`) read
`self.kwargs["tenant_id"]`, but every one of their URL patterns actually
captured the group as `place_id`. This is a guaranteed `KeyError` → 500
on literally every menu read/update/delete call — a second, independent,
100%-failure bug alongside the orders one, discovered only by tracing
the real request path rather than reading each file in isolation. Fixed
by renaming every URL capture group in `menu/api/urls.py` from
`place_id` to `tenant_id` to match what the views already expect.

### Bug 3 — Menu app: zero authentication/authorization (CRITICAL, highest-priority per item 3)
No menu view — create, bulk-create, list, detail, update, or delete, for
categories, items, extras, or item↔extra links — declared
`permission_classes`. This project has no
`DEFAULT_PERMISSION_CLASSES` set in `SmartRestaurant/settings.py`
(only `DEFAULT_AUTHENTICATION_CLASSES` is configured), so DRF's built-in
default of `AllowAny` applied to the entire menu app. Combined with bug
#2 (which made every *read* path 500 instead of leaking data), the
practical exposure was that **write** endpoints (create/bulk-create,
which take `tenant_id` from the request body, not the URL, so bug #2
didn't block them) were fully open: any unauthenticated caller could
create menu items/categories/extras for **any tenant** by supplying an
arbitrary `tenant_id`. This is a genuine, unauthenticated,
cross-tenant write vulnerability — the most severe finding in this
phase. Fixed by adding `IsAuthenticated` + the existing
`RequirePermission("menu.view"/"menu.edit")` RBAC gate (built in Z.4's
`access/authorization/tenant_access.py`, previously used only by
`access/api/views/memberships.py`) to every menu view, including a
manual `permission_selector.user_has_permissions(...)` check inside the
`create`/`bulk-create` views (their tenant id isn't in the URL, so the
declarative `RequirePermission` class can't resolve it there).

### Bug 4 — `RequirePermission`'s denial path itself was broken
While testing the menu fix, every permission-denied case 500'd instead
of returning 403. `BaseTenantPermission.has_permission()` (in
`access/authorization/tenant_access.py`) raised
`PermissionDeniedException(detail=...)`, but
`core.exceptions.BaseAppException.__init__` only accepts `message`, not
`detail`. **This means the exact RBAC mechanism Z.4 verified and relied
on (`RequirePermission`, used by `TenantMembershipRetrieveUpdateView`
etc.) has been silently 500ing on every denied-permission call since it
was introduced** — Z.4's tests only exercised the *allowed* path. Fixed
the one line (`detail=` → `message=`). This is a pre-existing latent bug
in already-"verified" code, not something introduced in this phase, and
is called out explicitly per this phase's honesty requirement.

### Bug 5 — `tenant_id` typed as `IntegerField` in four request/response serializers
`Tenant.id` is a `UUIDField` primary key (per `BACKEND_SCHEMA.dbml` and
`tenants/models/tenant.py`), but `menu/api/serializers/request/item.py`,
`menu/api/serializers/request/category.py`, and
`orders/api/serializers/request/orders.py`/`response/orders.py` all
declared `tenant_id = serializers.IntegerField()`. A DRF `IntegerField`
rejects any UUID string outright, so **every** menu-item/category create
call and the orders discount-validation endpoint would fail input
validation on any real tenant id. Fixed all four to `UUIDField`. (The
menu URL path parameters had the same problem — `<int:tenant_id>` can
never match a UUID — fixed alongside bug #2's rename, now
`<uuid:tenant_id>`.)

### Bug 6 — Menu URL params for non-tenant ids (`pk`, `category_id`, `item_id`, `extra_id`) are untouched
These remain plain Django auto-increment integers (`MenuCategory`,
`MenuItem`, `Extra`, `MenuItemExtra` all use the default integer PK), so
no change was needed there — only the tenant-id-shaped params needed the
UUID fix.

## 3. Security issues fixed
Summarized here for visibility (details in §2):
1. **Menu app fully unauthenticated write access, any tenant** (bug #3) — highest severity, fixed.
2. **`RequirePermission` denial path 500ing instead of denying with 403** (bug #4) — a real availability/consistency bug in the RBAC primitive itself; not an authz bypass (unauthenticated/unauthorized requests still fail, just with the wrong status code and a stack trace), but still a genuine defect, fixed.
3. Confirmed **no permission-result caching anywhere** in the codebase (`access/`, `core/`) — grepped for `cache` across both, zero hits. There is nothing to leak across tenants because nothing is cached. Documented rather than invented.

## 4. Re-verified items (no regression found)
- `GET /api/auth/me/`, `GET /api/tenants/me/`,
  `GET /api/tenants/<id>/branches/` — re-ran the full Z.4 test suite
  (`access/tests/test_schema_alignment.py`), all pass unmodified; shapes
  match the frozen contract.
- No `user.role`/`User.role`/`tenant.owner`/`Tenant.owner`/`is_owner`
  reintroduced anywhere (grepped repo-wide). The only textual hits are
  exception class names (`StaffMembershipNotFoundException`, etc.) and a
  role-slug string `Role.OWNER = "owner"` — both cosmetic, not model
  references, left as-is (renaming would be pure churn, same call Z.4
  made for `NotTenantOwnerException`'s error code).
- `tenants/api/views/tenant.py`'s `TenantRetrieveAPIView`/
  `BranchRetrieveAPIView` remain fully `AllowAny` (no
  `permission_classes` set, and — as newly confirmed this phase — no
  project-wide `DEFAULT_PERMISSION_CLASSES` either). This was flagged in
  Z.4 as "documented, not changed, pending human sign-off on whether
  public tenant/branch read is intentional (customer storefront) or a
  bug." Left as-is again this phase for the same reason — locking it
  down is a product decision, not a bugfix, and is explicitly out of
  this phase's "no new features/behavior changes beyond fixing broken
  existing code" mandate. Still flagged for sign-off.
- JWT issuance (`accounts/services/auth_service.py`,
  `rest_framework_simplejwt.tokens.RefreshToken.for_user`) uses only
  default simplejwt claims — no custom `role`/`tenant_id` claims are
  injected anywhere, so there's no stale-claim risk. Confirmed by
  reading the full auth service file; no `role`/`tenant`/`owner` tokens
  appear in it at all except the import statement itself.
- No first-login/new-user special-casing in the `/auth/me/` path — it's
  one plain `TenantMembership.objects.filter(...)` query regardless of
  account age, confirmed by re-reading `accounts/api/views/auth.py`.
- Websocket auth (`core/middleware/websocket_auth.py`) resolves
  `User.objects.get(id=validated_token["user_id"])` from a verified JWT,
  not client-supplied data — safe, matches Z.4's finding.

## 5. Tests added
- `access/tests/test_schema_alignment.py`: `AuthTokenValidityTests` (3
  tests — garbage token, missing token, tampered token, all → 401).
- `orders/tests/test_orders_runtime.py` (new file, 8 tests): order
  creation against real fields/totals; status-update denied with no
  permission; allowed with `orders.edit`; denied cross-tenant; denied/
  allowed under `branch_scope=selected`; customer order isolation
  (detail 404, list scoped to own orders).
- `menu/tests/test_menu_runtime.py` (new file, 7 tests):
  unauthenticated denied (list/create); member without permission denied
  (create); member with `menu.edit` allowed (create); cross-tenant
  denied (create for a tenant the caller has no membership in); own-
  tenant list allowed; cross-tenant list denied; item list
  allowed/denied analogously.

**Full run**, live Postgres 16 + Redis (`/tmp/venv`,
`POSTGRES_DB=backsamoon`):
- `python manage.py test` → **41/41 passing** (21 pre-existing from
  Z.3/Z.4 + 3 new token-validity + 8 new orders + 7 new menu, plus 2
  pre-existing orders/menu app scaffolding tests were absent before this
  phase — the 41 total reflects all of the above).
- `python manage.py check` → clean, no issues.
- `python manage.py makemigrations --check --dry-run` → no changes
  detected (no model changes were made this phase — only
  selectors/services/serializers/views/urls).

## 6. Remaining technical debt (found, deliberately not fixed, with reasoning)
- **`TenantRetrieveAPIView`/`BranchRetrieveAPIView` AllowAny** (§4) —
  carried forward from Z.4, still needs explicit human sign-off on
  intended public-read behavior before it can be "fixed" one way or the
  other.
- **Discount codes are entirely unimplemented** — `orders_dal.
  get_discount_by_code` is a placeholder returning `None` always
  (pre-existing, documented in the code itself as "Placeholder until a
  real Discount/Coupon model exists"). `validate_discount`/order
  creation both treat any non-empty discount code as invalid. This is
  pre-existing, explicitly flagged in the code as intentional-for-now,
  and building a real Discount model is new-feature territory,
  explicitly out of scope.
- **`Address` reuse on order edit** — `detach_delivery_address` now
  correctly detaches the FK instead of trying (and failing) to delete a
  non-existent reverse relation, but a guest checkout's one-off
  `Address` row becomes orphaned (unreferenced) after an edit replaces
  it. This is a minor data-hygiene issue, not a security or correctness
  bug (no cross-tenant/cross-user leak — `Address.user` stays correctly
  scoped), left as a known minor inefficiency rather than adding
  cleanup logic beyond this phase's bugfix mandate.
- **`OrderItem.image` snapshot** — now populated from
  `menu_item.image.name` if present, but this stores the raw storage
  path, not a resolved URL; consistent with how the rest of the codebase
  handles `ImageField` snapshots (not changed, not a regression).
- **Menu app has no branch-level scoping at all** — confirmed
  intentional per the schema: `MenuCategory`/`MenuItem`/`Extra` are all
  tenant-scoped only (`tenant` FK, no `branch` FK), so "branch-scoped
  menu" is not a concept this schema supports. `branch_scope=selected`
  therefore correctly has no bearing on menu endpoints (only on
  order status updates, which do belong to a specific `Branch`). Noted
  per item 4's explicit instruction to report when branch-scoping is
  N/A rather than inventing a check.
- **No "Tables/Inventory/Reports" apps exist in this codebase** —
  confirmed absent, not invented, per item 4's explicit instruction.
- The four Z.4 "requires human sign-off" decisions (extra Tenant/Branch
  columns, `WorkingHour` vs `business_hours` duplication, invite/pending
  membership state, `activeMembership` resolution rule) were not
  re-litigated per this phase's explicit instructions — they remain
  open, documented in `docs/BACKEND_CONTRACT_VERIFICATION_REPORT.md`
  §5.

## 7. Honesty notes
- Bug #4 (`RequirePermission`'s `detail=` TypeError) was discovered only
  because this phase's new menu-permission tests exercised the *denied*
  path — Z.4's own tests for the same mechanism
  (`access/api/views/memberships.py`) only ever exercised the *allowed*
  path, so the bug was latent and unverified in "already verified" code.
  This is called out explicitly rather than silently folded into "menu
  fixes," since it affects `access`, an app Z.4 marked as fully audited.
- All orders and menu fixes in this report were verified by real,
  passing tests against live Postgres — not by code inspection alone,
  unlike one item in Z.4's report that was explicitly caveated as
  inspection-only.
- Import order in `access/tests/test_schema_alignment.py` was not
  reorganized; the new `AuthTokenValidityTests` class was appended at
  the end to minimize diff noise, matching this repo's existing test
  file conventions.
