# Tenant Detail Lookup: UUID → Slug Contract Migration

## Summary

`GET /api/tenants/{tenant_id}/` (UUID) → `GET /api/tenants/{tenant_slug}/`
(slug). This is the public/frontend-facing tenant detail endpoint the
console flow resolves tenants through; response body is unchanged — it
still contains the tenant's UUID `id` for internal relations, only the
URL's lookup key changed. All other tenant-scoped endpoints (update,
delete, branches, memberships, menu) remain UUID-based intentionally —
see "Audit: endpoints kept UUID-based" below.

## Files changed

- `tenants/api/urls.py` — the `tenant-detail` route's path converter
  changed from `<uuid:tenant_id>/` to `<slug:tenant_slug>/`. No other
  route in this file changed. (Django's built-in `slug` converter regex
  is `[-a-zA-Z0-9_]+`, which is a superset of what a UUID string
  contains — a raw UUID still *routes* to this view, but no longer
  resolves a tenant, since it won't match any real `slug` value. See
  "UUID lookup no longer required" below.)
- `tenants/api/views/tenant.py` — `TenantRetrieveAPIView.retrieve()` now
  reads `kwargs["tenant_slug"]` and calls the new
  `tenant_bll.get_tenant_by_slug(...)`. `TenantResponseSerializer` is
  unchanged — response shape is identical to before.
- `tenants/services/tenant_bll.py` — `get_tenant(tenant_id)` renamed to
  `get_tenant_by_slug(tenant_slug)`, now backed by
  `tenant_dal.get_tenant_by_slug(...)`. Confirmed via grep this was the
  only call site (`tenants/api/views/tenant.py`'s retrieve view) — no
  other code depended on the old signature.
- `tenants/selectors/tenant_dal.py` — added `get_tenant_by_slug(slug)`
  (`Tenant.objects.filter(slug=slug).first()`, returns `None` rather than
  raising, matching the existing `get_tenant_by_id` pattern). The
  pre-existing `get_by_slug()` method (a `.get()` that raises
  `Tenant.DoesNotExist`) was unused before this change and is left
  as-is — not part of this task's scope to remove.
- Tests updated: `tenants/tests/test_public_settings.py` — 3 tests that
  called `GET /api/tenants/{tenant.id}/` switched to
  `GET /api/tenants/{tenant.slug}/` (the settings-contract behavior they
  test is unaffected — only the URL changed).
- `tenants/tests/test_tenant_slug_lookup.py` (new) — the dedicated test
  suite for this migration (see below).

## Migration changes

**None.** `Tenant.slug` was already `SlugField(unique=True)` — Django
backs `unique=True` with a real database unique constraint/index
automatically. Verified directly against the live Postgres schema:

```
Indexes:
    "tenant_slug_812ad82d_like" btree (slug varchar_pattern_ops)
    "tenant_slug_key" UNIQUE CONSTRAINT, btree (slug)
```

No model field changed, so no migration was needed or generated
(`makemigrations --check --dry-run` confirms no pending changes).

## /me contract

Unchanged — already correct before this task. `accounts/api/views/auth.py::MeView`
already returns both `tenantId` and `tenantSlug` per membership:

```json
{"tenantId": "...", "tenantSlug": "...", "roles": [...], "branchAccess": {...}}
```

No removal, no breaking change. New test
`AuthMeTenantIdAndSlugTests.test_me_returns_both_tenant_id_and_slug`
confirms both fields are present and that the returned `tenantSlug` is
directly usable against the now-slug-based tenant detail endpoint
end-to-end.

## Audit: endpoints kept UUID-based (intentional)

Per the instruction to migrate the lookup contract "where frontend-facing
tenant resolution is involved" and not change business logic elsewhere,
the following remain UUID-keyed:

| Endpoint | Why kept UUID-based |
|---|---|
| `PUT/PATCH /api/tenants/{tenant_id}/update/`, `DELETE /api/tenants/{tenant_id}/delete/` | Authenticated mutation endpoints gated by `_assert_owns_tenant` (resolves ownership via `TenantMembership`), not public routing — the caller already has the tenant's UUID from a prior `/auth/me/` or detail-by-slug response. |
| `GET/POST /api/tenants/{tenant_id}/branches/...` (create/update/delete/detail) | Branch endpoints resolve membership/RBAC via `TenantMembership.objects.filter(tenant_id=..., ...)` — internal relational lookups, reached only after the caller already has the tenant's UUID (from `/auth/me/` or the tenant detail response's `id` field). |
| `access/api/urls.py`'s `tenants/{tenant_id}/memberships/...` (membership CRUD, role/branch assignment) | RBAC/permission-management endpoints — `permission_dal.user_has_permissions(tenant_id=...)` and every membership relation are keyed by the tenant's UUID throughout the schema; these aren't part of the public tenant-resolution/routing flow. |
| `menu/api/urls.py`'s `<uuid:tenant_id>/...` (categories, items, extras) | Menu content management, gated by `RequirePermission("menu.view"/"menu.edit")`, which resolves via `TenantMembership` by UUID — internal to an already-resolved tenant context, not a public routing entry point. |
| `POST /api/tenants/create/` | Creates a new tenant; no lookup involved. |

None of these "unexpectedly require UUID when called from frontend
routing" — they're all reached only *after* the frontend has already
resolved the tenant (by slug, via the newly-changed detail endpoint, or
via `/auth/me/`'s `tenantId`), matching the console flow: resolve tenant
by slug once, then use its UUID for every subsequent authenticated
operation within that tenant's context. Settings/feature-flag resolution
lives entirely on the `Tenant.settings` JSON field returned by the (now
slug-based) detail endpoint itself — there's no separate
settings/features endpoint to audit.

## Tests

`tenants/tests/test_tenant_slug_lookup.py` (6 tests):
- `test_retrieve_by_slug_returns_tenant` — `GET /api/tenants/{slug}/`
  returns 200 with the correct tenant.
- `test_invalid_slug_returns_404` — an unknown slug 404s.
- `test_uuid_lookup_is_no_longer_required_or_accepted` — the old
  UUID-based URL now 404s (a UUID string doesn't match any real slug).
- `test_retrieve_by_slug_works_without_authentication` — public, no auth
  required (matches the discover endpoint's access model; this also
  resolves the long-standing open question from prior phases about
  whether tenant detail should be public — confirmed yes, for the
  console/frontend routing flow).
- `test_response_shape_unchanged` — exact field-set assertion.
- `AuthMeTenantIdAndSlugTests.test_me_returns_both_tenant_id_and_slug` —
  `/auth/me/` still returns both `tenantId` and `tenantSlug`, and the
  slug round-trips correctly against the detail endpoint.

## Verification

- `python manage.py check` — clean.
- `python manage.py test` — **73/73 passing** (67 pre-existing + 6 new).
- `python manage.py makemigrations --check --dry-run` — no changes
  detected.
