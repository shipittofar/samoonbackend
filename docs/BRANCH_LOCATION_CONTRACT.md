# Branch location contract (service area, pin verification, discover)

Implements the frontend's Phase L1–L3 location features
(`samoon_Q/docs/PHASE_L1_SERVICE_AREA_API_CONTRACT.md`). A **business (tenant) has no
location of its own** — maps, distance and "near me" are always computed per **branch**.

## New branch fields

| Model field | API field | Notes |
|---|---|---|
| `Branch.service_area` (JSON, nullable) | `serviceArea` | `null` = no custom area; clients fall back to the delivery radius, then the business-type default |
| `Branch.location_verified_at` (datetime, nullable) | `locationVerifiedAt` | when the owner confirmed the pin is exact; **always server time**; `null` = unverified |

Migration: `tenants/migrations/0019_branch_service_area_location_verified.py`.

### `serviceArea` shape

```json
{
  "mode": "delivery | on_site | visit_only",
  "shape": { "type": "circle", "radiusKm": 6 },
  "zones": [{ "upToKm": 3, "fee": 0, "etaMinutes": 30 }]
}
```

- `shape` is a circle (`0 < radiusKm ≤ 500`) or a polygon (`3–200` points `{lat, lng}`, no `0,0`).
- `zones` are optional, `upToKm` strictly ascending and within the radius, `fee ≥ 0`, `etaMinutes ≥ 0`.
- Unknown keys are dropped. Validation: `tenants/service_area.py::validate_service_area`.

### Writes (console create / `PATCH /api/branches/{id}/`)

- `serviceArea`: object sets, `null` clears, omitted = unchanged. Also accepted as a JSON
  string in multipart bodies.
- `locationVerifiedAt`: the stored value is **never the client's clock**
  (`tenants/service_area.py::resolve_location_verified_at`):
  - a new non-null value = a fresh owner confirmation → stored as server time;
  - `null` clears it;
  - the same value that is already stored (the form echoing it back) keeps it;
  - **moving the pin** (latitude/longitude change) without a confirmation in the same
    request resets it to `null`.
- The legacy full-replace `PUT` resets the confirmation when the coordinates change, too.

### Reads

`BranchResponseSerializer` (branch detail/list) returns `serviceArea` and `locationVerifiedAt`.

## Discover (`GET /api/public/discover/`)

Each entry of `branches[]` additionally carries:

| field | notes |
|---|---|
| `location.latitude`, `location.longitude` | the branch pin (decimal, nullable) |
| `serviceArea`, `locationVerifiedAt` | as above |
| `menuItemNames` | names of the branch's **published and orderable** items (`is_active` and `available`), de-duplicated, popular first, capped at `MAX_MENU_NAMES_PER_BRANCH` (300) |
| `menuCategoryNames` | the branch's category names |

The tenant object itself has no coordinates.

**Freshness:** the discover list is cached (`CacheKeys.DISCOVER_LIST`, TTL 10 minutes).
Branch writes refresh it immediately; menu item/category writes do not, so new menu text
appears in discover within the cache TTL.
