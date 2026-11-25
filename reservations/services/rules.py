"""How a branch takes reservations: slot spacing, length, limits.

Each value is looked up in this order; an empty one falls through:
  1. the branch's own value (BranchReservationRules, set by the business)
  2. the platform's value for the business type (platform panel)
  3. the platform's value for everybody (platform panel)
  4. the built-in value for the business type, then for everybody (below)
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from reservations.models import BranchReservationRules
from tenants.constants.business_type import BusinessType

SETTINGS_KEY = "reservations.rules"

# field: (smallest, largest) allowed value
LIMITS = {
    "slot_minutes": (5, 720),
    "duration_minutes": (5, 1440),
    "last_before_close_minutes": (0, 1440),
    "lead_minutes": (0, 43200),
    "max_days_ahead": (1, 365),
    # Reservations at the same time (chairs, rooms, specialists). Empty = no limit.
    "max_concurrent": (1, 1000),
}
FIELDS = tuple(LIMITS)

BUILT_IN = {
    "slot_minutes": 30,
    "duration_minutes": 120,
    "last_before_close_minutes": 60,
    "lead_minutes": 60,
    "max_days_ahead": 60,
    "max_concurrent": None,
}
BUILT_IN_BY_TYPE = {
    "beauty_salon": {"slot_minutes": 60, "duration_minutes": 60, "last_before_close_minutes": 60},
    "clinic": {"slot_minutes": 30, "duration_minutes": 30, "last_before_close_minutes": 30},
    "gym": {"slot_minutes": 60, "duration_minutes": 60, "last_before_close_minutes": 60},
}
TYPES = tuple(BusinessType.values)


def _clean(data, where: str) -> dict:
    """{field: int} from user input; empty values are dropped (= inherit)."""
    if not isinstance(data, dict):
        raise ValidationError({where: "Expected an object."})
    out = {}
    for field in FIELDS:
        raw = data.get(field)
        if raw in (None, ""):
            continue
        try:
            value = int(str(raw))
        except ValueError:
            raise ValidationError({field: "A whole number is required."})
        low, high = LIMITS[field]
        if isinstance(raw, bool) or not low <= value <= high:
            raise ValidationError({field: f"Between {low} and {high}."})
        out[field] = value
    return out


# ── Platform ─────────────────────────────────────────────────────────────────


def platform_rules() -> dict:
    from platform_settings.models import PlatformSetting

    row = PlatformSetting.objects.filter(key=SETTINGS_KEY).first()
    stored = row.value if row and isinstance(row.value, dict) else {}
    by_type = stored.get("by_type") if isinstance(stored.get("by_type"), dict) else {}
    return {"default": stored.get("default") or {}, "by_type": {t: by_type.get(t) or {} for t in TYPES}}


def admin_view() -> dict:
    """The platform's own values plus what applies where they are empty."""
    own = platform_rules()
    return {
        **own,
        "inherited": {
            "default": BUILT_IN,
            "by_type": {t: _platform_effective(own, [t], include_own_type=False) for t in TYPES},
        },
        "limits": {f: list(v) for f, v in LIMITS.items()},
    }


def save_platform_rules(data, *, actor) -> dict:
    from platform_settings.models import PlatformSetting, PlatformSettingChange

    data = data if isinstance(data, dict) else {}
    by_type = data.get("by_type") or {}
    if not isinstance(by_type, dict) or set(by_type) - set(TYPES):
        raise ValidationError({"by_type": "Unknown business type."})
    value = {
        "default": _clean(data.get("default") or {}, "default"),
        "by_type": {t: cleaned for t in TYPES if (cleaned := _clean(by_type.get(t) or {}, t))},
    }
    with transaction.atomic():
        row = PlatformSetting.objects.select_for_update().filter(key=SETTINGS_KEY).first()
        previous = row.value if row else None
        row = row or PlatformSetting(key=SETTINGS_KEY)
        row.value, row.updated_by = value, actor
        row.save()
        PlatformSettingChange.objects.create(key=SETTINGS_KEY, previous_value=previous, new_value=value, changed_by=actor)
    return admin_view()


def _platform_effective(platform: dict, business_types, *, include_own_type: bool = True) -> dict:
    rules = dict(BUILT_IN)
    kind = next((t for t in business_types or [] if t in TYPES), None)
    rules.update(BUILT_IN_BY_TYPE.get(kind, {}))
    rules.update(platform["default"])
    if kind and include_own_type:
        rules.update(platform["by_type"].get(kind) or {})
    return rules


# ── Branch ───────────────────────────────────────────────────────────────────


def own_rules(branch) -> dict:
    row = BranchReservationRules.objects.filter(branch=branch).first()
    return {f: getattr(row, f) if row else None for f in FIELDS}


def inherited_rules(branch) -> dict:
    """What applies to the branch where it has no value of its own."""
    return _platform_effective(platform_rules(), branch.tenant.business_types)


def rules_for(branch) -> dict:
    own = {f: v for f, v in own_rules(branch).items() if v is not None}
    return {**inherited_rules(branch), **own}


def branch_view(branch) -> dict:
    return {
        "own": own_rules(branch),
        "inherited": inherited_rules(branch),
        "effective": rules_for(branch),
        "limits": {f: list(v) for f, v in LIMITS.items()},
        "max_capacity": branch.max_capacity,
    }


def save_branch_rules(branch, data, *, actor) -> dict:
    cleaned = _clean(data, "rules")
    BranchReservationRules.objects.update_or_create(
        branch=branch, defaults={**{f: cleaned.get(f) for f in FIELDS}, "updated_by": actor}
    )
    return branch_view(branch)
