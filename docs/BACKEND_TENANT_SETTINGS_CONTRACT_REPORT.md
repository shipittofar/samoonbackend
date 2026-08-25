# Phase Z.6.4 — Tenant.settings Marketplace Contract Report

## Root cause

The first pass at this phase (superseded by this report) implemented
`Tenant.settings` as a deep-merge-over-hardcoded-defaults contract: a new
`DEFAULT_TENANT_SETTINGS` constant baked the entire example payload
(`featureFlags` all `true`, `theme.primaryColor: "#1a1a2e"`, every
`marketplace` field defaulted to `""`/`0`/`false`/`[]`) into the backend,
and every read/write path merged stored data over that hardcoded
structure. That directly violates this phase's explicit rules: **no
default values, no hardcoded marketplace configuration, no generated
fallback settings**. It also silently reshaped caller data — a partial
`settings` payload would come back padded with invented keys the caller
never sent, and an update with a narrower `settings` object would still
show the *previous* write's values bleeding through via the merge instead
of being replaced.

This report corrects that: `Tenant.settings` is now a pure passthrough
JSON configuration object. The backend stores and returns exactly what
API input or admin configuration provides — nothing added, nothing
dropped, nothing reshaped.

## Files changed

- `tenants/models/tenant_settings.py` — **deleted**. This module held
  `DEFAULT_TENANT_SETTINGS` and `merge_tenant_settings()`, both of which
  hardcoded marketplace configuration and generated fallback values;
  removing it is the core fix.
- `tenants/models/tenant.py` — removed the `get_settings()` method (it
  only existed to call the now-deleted merge helper). Kept
  `get_feature_flag(flag, default=False)` but rewrote it to be a pure
  read accessor: it reads `self.settings.get("featureFlags", {})`
  directly (no merge, no full-shape fabrication) and returns exactly the
  caller-supplied `default` argument when the flag is absent — it never
  writes back to `settings` and never invents any other part of the
  configuration.
- `tenants/api/serializers/request/tenant_request.py` — `validate_settings()`
  rewritten from a multi-key structural validator (which rejected
  `featureFlags`/`theme`/`marketplace` if present-but-wrong-shape, and
  validated every `marketplace` list field and each `branches[]` entry)
  down to a single check: `settings` must be a JSON object if provided
  (or empty). No nested key, either at the top level or inside
  `marketplace`, is required, defaulted, or shape-checked — per "do not
  restrict marketplace fields unnecessarily."
- `tenants/api/serializers/response/tenant_response.py` — both
  `TenantResponseSerializer` and `PublicTenantResponseSerializer` had
  `settings` changed from a `SerializerMethodField` (calling the deleted
  merge-based `get_settings()`) back to a plain `ModelSerializer` field —
  a direct passthrough of the stored JSONField, unchanged.
- `tenants/api/views/tenant.py` — `MyTenantListAPIView` (`GET
  /api/tenants/me/`) now returns `membership.tenant.settings` (raw)
  instead of `membership.tenant.get_settings()` (merged). The additive
  `settings` key added to this endpoint's response in the prior pass is
  kept — that part of the change (making all three tenant endpoints
  return `settings`) was correct and is unaffected by this fix.
- `tenants/services/tenant_bll.py` — removed both `merge_tenant_settings(...)`
  calls from `create_tenant`/`update_tenant`. `settings` is now stored
  exactly as received from the request serializer, with no
  transformation. This restores tenant creation/update to its pre-Z.6.4
  behavior for every field except `settings` itself, per the instruction
  "do not modify existing tenant creation behavior except allowing the
  settings payload to be stored and returned."
- `tenants/tests/test_public_settings.py` — rewritten. Every test that
  asserted merge-with-defaults behavior (`DEFAULT_TENANT_SETTINGS`
  equality, "untouched keys fall back to defaults," etc.) is replaced
  with tests asserting exact passthrough: what's sent is exactly what's
  stored and returned, a payload with unconventional/unknown fields
  round-trips unchanged, an update replaces the stored value verbatim
  (no merge with the previous value), and an omitted `settings` on
  create stores literal `{}` rather than any invented structure.
- `tenants/tests/test_public_tenants.py` — `test_full_tenant_fields_are_returned`'s
  settings assertion updated from "merged with defaults" back to "exact
  passthrough of what was stored."

## Verified: Tenant.settings JSONField behavior

- Accepts arbitrary nested JSON objects — confirmed via
  `test_create_does_not_restrict_marketplace_field_shapes`, which posts a
  payload with an unconventional field type (`rating` as a string) and an
  entirely unknown key (`customTopLevelKey`) and confirms both survive
  unchanged.
- Does not remove unknown keys — same test.
- Does not transform the structure — confirmed via
  `test_no_settings_data_lost_during_serialization`, which round-trips
  the full example payload from the task spec (including the nested
  `marketplace.branches[]` array) through create → store → retrieve and
  asserts byte-for-byte equality at every level.

## API contract: before/after

| Endpoint | Before (first-pass Z.6.4) | After (this correction) |
|---|---|---|
| `GET /api/tenants/`, `GET /api/tenants/{id}/`, `GET /api/tenants/me/` | `settings` deep-merged over a hardcoded default shape — a stored `{}` or partial object always came back padded with invented `featureFlags`/`theme`/`marketplace` defaults | `settings` returned exactly as stored — `{}` stays `{}`, a partial object stays partial, nothing is added |
| `POST /api/tenants/create/`, `PUT/PATCH /api/tenants/{id}/update/` | `settings` validated with strict per-key type checks (each of `featureFlags`/`theme`/`marketplace`, each marketplace list field, each `branches[]` entry) and persisted after being merged over hardcoded defaults | `settings` only checked for "is this a JSON object" and persisted exactly as sent — no merge, no defaulting, no key-level shape enforcement |
| `tenant.get_feature_flag(flag)` | Called a full-structure merge (`get_settings()`) before reading the flag | Reads `settings.featureFlags` directly; returns the caller's `default` argument (not a hardcoded value) when absent |

Existing fields (`id`, `name`, `slug`, `image`, `business_types`,
`status`, `tax_percentage`, `created_at`, `updated_at`) are unchanged in
both serializers — confirmed unaffected by this diff (no edits to their
field lists).

## Compliance with the phase's explicit rules

- **No default values added** — `DEFAULT_TENANT_SETTINGS` deleted;
  nothing replaces it.
- **No seed data created** — none existed before, none added now.
- **No hardcoded marketplace configuration** — the example payload from
  the task spec appears only inside a test file (`FULL_SETTINGS`, used to
  assert round-trip fidelity), never in application code.
- **No fallback settings generated** — an empty/omitted `settings`
  payload stores and returns literal `{}`.
- **Tenant creation behavior unmodified** beyond allowing the `settings`
  payload through — `create_tenant`/`update_tenant`'s only settings-related
  change versus the pre-Z.6.4 (original, pre-this-whole-phase) code is
  that `settings` continues to be a normal pass-through field, exactly as
  it always was; the intervening merge-based logic has been fully removed.
- **No new models, no new endpoints, no database architecture change** —
  `Tenant.settings` remains the same `JSONField(default=dict, blank=True)`
  it always was; no migration was needed or created.

## Test results

- `python manage.py check` — clean.
- `python manage.py test` — **61/61 passing**.
- `python manage.py makemigrations --check --dry-run` — no changes
  detected.
