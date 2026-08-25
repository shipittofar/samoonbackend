# Public Tenant Discovery Regression Fix

## Regression

`GET /api/tenants/` is the public tenant-discovery listing the frontend's
discover page (`usePublicTenants()` in `src/services/tenant.service.ts`)
consumes anonymously. During Phase Z.4's tenant-isolation hardening pass,
this endpoint was misread as an unscoped "list every tenant" admin leak
and restricted to `is_staff` users only (`docs/BACKEND_CONTRACT_VERIFICATION_REPORT.md`
§2 documents the change at the time). That was a mistake: this route was
never a per-user membership view — `GET /api/tenants/me/` (added in Z.3)
already covers "tenants I'm a member of." `GET /api/tenants/` is, and was
always meant to be, a public storefront directory, and locking it to staff
broke the discover page for every anonymous/unauthenticated visitor.

## Fix

`tenants/api/views/tenant.py::TenantListAPIView`:
- `permission_classes = ()`, `authentication_classes = ()` — fully public
  again, same as before Z.4's regression.
- `get_queryset()` now calls `tenant_bll.get_public_tenants()`
  (`tenants/services/tenant_bll.py` -> `tenants/selectors/tenant_dal.py`),
  which filters to `status="active"` and `is_active=True` only — trial,
  suspended, churned, and archived tenants, and any tenant with the legacy
  `is_active=False` soft-disable flag, are excluded from public discovery.
- `serializer_class = PublicTenantResponseSerializer` (new, in
  `tenants/api/serializers/response/tenant_response.py`) — returns only
  `id`, `name`, `slug`, `image`, `business_types`. Deliberately excludes
  `tax_percentage`, `settings`, `status`, `created_at`, `updated_at`, and
  every other field `TenantResponseSerializer` exposes for authenticated
  tenant-management flows (`TenantRetrieveAPIView`, `TenantUpdateAPIView`).
  `settings` in particular can carry operational config (contact email,
  business hours metadata, marketplace flags per the DBML's own note on
  that field) that has no business being public.

No URL changed. No new route was added. `GET /api/tenants/me/` (private,
membership-scoped) and `GET /api/tenants/` (public, discover) remain two
separate, already-existing endpoints with distinct purposes — this fix
only restores the second one's original public behavior and tightens its
response shape, it does not merge or redesign them.

## Why RBAC elsewhere is untouched

Every other tenant/branch endpoint that was locked down in Z.3/Z.4/Z.5
(`/tenants/me/`, `/tenants/<id>/branches/`, tenant create/update/delete,
branch create/update/delete, menu, orders) stays exactly as hardened —
none of those are the public discover flow, and none were changed here.
Only the one route the frontend's discover page actually depends on was
reverted to public.

## Follow-up: full tenant object requested

A subsequent request expanded `PublicTenantResponseSerializer` from the
minimal `{id, name, slug, image, business_types}` set to the full public
tenant object the frontend actually requires: adds `type`, `status`,
`tax_percentage`, `settings`, `created_at`, `updated_at`. Same URL, same
view, same underlying queryset (still filtered to `status="active"` and
`is_active=True`) — only the serializer's field list changed.

`Tenant` has no owner FK, membership relation, or permission/role data on
it at all (that architecture lives entirely on the separate
`TenantMembership` model, never referenced by this serializer), so
widening the field list to "every remaining Tenant column" does not
expose any ownership/RBAC data. `is_active` (the legacy admin soft-disable
toggle, already used server-side to filter this exact queryset) remains
excluded as the one field kept off the public response.

## Tests added

`tenants/tests/test_public_tenants.py` (4 tests, all passing against live
Postgres):
- `test_anonymous_request_returns_active_public_tenants` — an anonymous
  `APIClient` (no auth) gets a 200 and sees an active tenant.
- `test_inactive_tenants_are_excluded` — trial/suspended/churned/archived
  tenants and an `is_active=False` tenant are all excluded; only the one
  active+is_active tenant appears.
- `test_response_shape_matches_discover_contract` — response items contain
  exactly `{id, name, slug, image, business_types}`, nothing else.
- `test_no_sensitive_tenant_fields_leaked` — a tenant with `tax_percentage`
  and `settings` set does not leak either field (or `created_at`/
  `updated_at`) in the public response.

## Verification

- `python manage.py test` — **46/46 passing** (41 pre-existing from
  Z.3/Z.4/Z.5 + 5 in `test_public_tenants.py`).
- `python manage.py check` — clean.
- `python manage.py makemigrations --check --dry-run` — no changes (this
  fix touched only views/serializers/selectors, no model changes).
