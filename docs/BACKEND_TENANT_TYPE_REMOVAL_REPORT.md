# Phase Z.6.3 — Tenant.type Removal Report

## Summary

`Tenant.type` (a `coffee`/`restaurant` choice field) is removed entirely.
The frontend contract no longer uses it, and it was never part of the
frozen `docs/BACKEND_SCHEMA.dbml` — it was one of the "extra columns kept
beyond the schema floor" flagged for future review back in Z.4/Z.5. This
phase resolves that by removing it.

## Files changed

- `tenants/models/tenant.py` — removed the `TenantType` choices class and
  the `Tenant.type` field.
- `tenants/models/__init__.py` — removed the `TenantType` export.
- `tenants/api/serializers/request/tenant_request.py` — removed the
  `TenantType` import and the `type` field from `TenantCreateSerializer`
  (inherited by `TenantUpdateSerializer`).
- `tenants/api/serializers/response/tenant_response.py` — removed `"type"`
  from `PublicTenantResponseSerializer.Meta.fields`. `TenantResponseSerializer`
  (used by `GET /api/tenants/{id}/`) never included `type` in the first
  place — no change needed there.
- `tenants/services/tenant_bll.py` — removed `tenant.type = data["type"]`
  and `"type"` from `update_tenant`'s `update_fields` list.
- `tenants/admin/tenant.py` — removed `type` from `list_display`,
  `list_filter`, and the create/edit `fieldsets`.
- `tenants/migrations/0004_remove_tenant_type.py` (new) — drops the
  column.
- Tests updated: `tenants/tests/test_public_tenants.py`,
  `access/tests/test_schema_alignment.py`,
  `menu/tests/test_menu_runtime.py`, `orders/tests/test_orders_runtime.py`
  — all had a `make_tenant()` test helper passing `type="restaurant"` to
  `Tenant.objects.create(...)`, which would now raise `TypeError` on a
  removed field; all four fixed to drop that kwarg.

## API responses verified

- `GET /api/tenants/` (public discover) — no longer returns `"type"`.
  New test `test_type_field_is_not_returned` in
  `tenants/tests/test_public_tenants.py` asserts this explicitly, and the
  existing `test_response_shape_matches_discover_contract`/
  `test_full_tenant_fields_are_returned` tests were updated to the new
  field set (unchanged otherwise: `id`, `name`, `slug`, `image`,
  `business_types`, `status`, `tax_percentage`, `settings`, `created_at`,
  `updated_at`).
- `GET /api/tenants/{id}/` (`TenantResponseSerializer`) — confirmed it
  never exposed `type`; no regression possible.
- `GET /api/tenants/me/` (`MyTenantListAPIView`) — hand-built response
  dict (`{id, name, slug, roles}`), never included `type`; no change
  needed.

## Fields kept, as required

`business_types`, `settings`, `status`, `tax_percentage`, `slug`, `image`
are all untouched — confirmed present in both response serializers and
the model.

## Search results

Repo-wide grep for `.type`, `tenant.type`, `TenantType` (excluding
migrations, which retain historical `type` field references as expected —
migration history is append-only and never rewritten):

- All application-code hits were `Tenant.type`/`TenantType` — removed, see
  above.
- Unrelated hits correctly left untouched: `type(...)` (Python builtin) in
  `access/authorization/tenant_access.py`'s `RequirePermission` factory;
  Django Channels message-type keys (`"type": "connection_established"`,
  `"type": "order.status.update"`) in `orders/ws/consumers.py` and
  `orders/ws/notifications.py` — these are a Channels protocol
  requirement, not a Tenant field, and have nothing to do with this task.

## Migration status

`tenants/migrations/0004_remove_tenant_type.py` — a plain, safe
`RemoveField` migration, depends on `0003_migrate_closed_status`. Applied
cleanly against the live Postgres 16 database used by the test suite
(`manage.py migrate tenants` — `OK`). No data migration was needed (no
replacement field, no data to preserve per the task's explicit "do not
replace it with another field" instruction).

## Test results

- `python manage.py check` — clean.
- `python manage.py makemigrations --check --dry-run` — no changes
  detected (migration is complete).
- `python manage.py test` — **47/47 passing** (46 pre-existing + 1 new:
  `test_type_field_is_not_returned`).
