# ExtraGroup Backend Implementation

This document describes the backend implementation of `ExtraGroup` — a branch-scoped
container for Extras (modifiers) that defines customer selection rules.

## Architecture

ExtraGroup follows the same layered pattern as every other menu entity:

```
HTTP → DRF View → Request Serializer → BLL → DAL → Database / Cache → Response Serializer
```

| Layer | Location |
|---|---|
| Model | `menu/models/extra_group.py` |
| DAL | `menu/selectors/extra_group_dal.py` |
| BLL | `menu/services/extra_group_bll.py` |
| Views | `menu/api/views/extra_group.py` |
| Serializers | `menu/api/serializers/request/extra_group.py`, `response/extra_group.py` |
| Exceptions | `core/exceptions/item.py` |
| Cache keys | `core/cache/key.py` (`EXTRA_GROUP_LIST`, `EXTRA_GROUP_DETAIL`) |

## Domain Model

`ExtraGroup` is a **container only** — it has no price and is not directly orderable.
It groups `Extra` records and stores selection rules:

- `selection_type`: `single` | `multiple`
- `required`, `min_selection`, `max_selection`
- `order`, `is_active`

Relationships:

```
Branch → ExtraGroup → Extra
MenuItem → MenuItemExtraGroup → ExtraGroup
MenuItem → MenuItemExtra → Extra   (materialized for Orders)
```

When extra groups are assigned to a menu item, `MenuItemExtra` links are
automatically synchronized from the group's available extras so existing
`orders_bll._validate_item_extras()` continues to work unchanged.

## API Endpoints

### Backend convention (path-based `branch_id`)

| Method | Path |
|---|---|
| POST | `/api/menu/create-extra-groups/` |
| GET | `/api/menu/{branch_id}/extra-groups/` |
| GET | `/api/menu/{branch_id}/extra-groups/{id}/` |
| PATCH | `/api/menu/update-extra-groups/{branch_id}/extra-groups/{id}/` |
| DELETE | `/api/menu/delete-extra-groups/{branch_id}/extra-groups/{id}/` |
| PATCH | `/api/menu/{branch_id}/extra-groups/reorder/` |

### Frontend aliases (query-param `branch_id`)

| Method | Path |
|---|---|
| GET/POST/PATCH | `/api/menu/extra-groups/?branch_id={id}` |
| GET/PATCH/DELETE | `/api/menu/extra-groups/{id}/?branch_id={id}` |
| PATCH | `/api/menu/items/{id}/?branch_id={id}` with `{ extra_group_ids: [...] }` |

## Validation Rules

Enforced in `ExtraGroupBusinessLogicLayer._validate_selection_rules`:

- Name unique per branch
- `min_selection >= 0`, `max_selection >= 1`, `min_selection <= max_selection`
- `required` implies `min_selection >= 1`
- `single` implies `max_selection == 1` and `min_selection in (0, 1)`
- Inactive groups cannot be assigned to menu items

## Migrations

| Migration | Purpose |
|---|---|
| `0002_extragroup` | Create `ExtraGroup` table |
| `0003_extra_group_fk_and_menuitemextragroup` | Add `Extra.group` (nullable), extra metadata fields, `MenuItemExtraGroup` |

`Extra.group` remains nullable for safe migration of existing installations.
A future migration can make it required after data backfill.

## Tests

Run:

```bash
python manage.py test menu.tests.test_extra_group
```

Covers validation rules, group assignment, materialization of `MenuItemExtra`,
and inactive-group rejection.
