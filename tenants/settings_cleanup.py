"""Tenant.settings contract: denylist of deprecated keys + allowlist of live keys.

Phase 1–4A keys are stripped (not rejected) so existing clients that still send
duplicated Branch/computed fields do not break.

Unknown keys that are not in that denylist are rejected on API writes.

``Tenant.save()`` only strips deprecated keys and preserves other stored JSON
so existing production extras are not deleted by unrelated saves. Direct
``QuerySet.update(settings=...)`` bypasses this module.

Open maps (not closed objects):
  - featureFlags: dotted string → bool
  - addressCapabilities: string → bool
"""
from __future__ import annotations

from typing import Any

from tenants.branding import validate_tenant_branding

PHASE1_TOP_LEVEL_KEYS = frozenset({
    "currency",
    "language",
    "timezone",
    "time_zone",
})

PHASE1_ORDERING_KEYS = frozenset({
    "dineIn",
    "dine_in",
    "delivery",
    "takeaway",
    "onlinePayment",
    "online_payment",
})

PHASE1_MARKETPLACE_KEYS = frozenset({
    "cuisines",
    "amenities",
    "openNow",
    "branchCount",
    "primaryBranchSlug",
})

PHASE2_MARKETPLACE_KEYS = frozenset({
    "city",
    "email",
    "phone_number",
    "description",
    "coverImage",
    "branches",
})

DEPRECATED_MARKETPLACE_KEYS = PHASE1_MARKETPLACE_KEYS | PHASE2_MARKETPLACE_KEYS

ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "theme",
    "featureFlags",
    "addressCapabilities",
    "marketplace",
    "contactEmail",
    "contactPhone",
    "notificationMatrix",
})

THEME_ALLOWED_KEYS = frozenset({
    "primaryColor",
    "accentHoverColor",
    "fontBody",
    "fontsByLocale",
})

MARKETPLACE_ALLOWED_KEYS = frozenset({
    "tagline",
    "featured",
    "priceLevel",
    "tags",
    "gallery",
    "rating",
    "reviewCount",
    "story",
    "website",
    "socialLinks",
    "heroImage",
    "popular",
    "isNew",
})

SOCIAL_LINKS_ALLOWED_KEYS = frozenset({
    "instagram",
    "twitter",
    "facebook",
    "youtube",
})

PUBLIC_SETTINGS_KEYS = frozenset({
    "theme",
    "featureFlags",
    "marketplace",
    "contactEmail",
    "contactPhone",
})


class TenantSettingsContractError(ValueError):
    """Raised when API-bound settings violate the explicit contract."""


def strip_deprecated_tenant_settings(settings: Any) -> dict:
    """Return a copy of settings with deprecated duplicated/computed keys removed."""
    if not isinstance(settings, dict):
        return {}

    cleaned = dict(settings)

    for key in PHASE1_TOP_LEVEL_KEYS:
        cleaned.pop(key, None)

    ordering = cleaned.get("ordering")
    if isinstance(ordering, dict):
        ordering = {
            key: value
            for key, value in ordering.items()
            if key not in PHASE1_ORDERING_KEYS
        }
        if ordering:
            cleaned["ordering"] = ordering
        else:
            cleaned.pop("ordering", None)

    cleaned.pop("features", None)

    marketplace = cleaned.get("marketplace")
    if isinstance(marketplace, dict):
        marketplace = {
            key: value
            for key, value in marketplace.items()
            if key not in DEPRECATED_MARKETPLACE_KEYS
        }
        if marketplace:
            cleaned["marketplace"] = marketplace
        else:
            cleaned.pop("marketplace", None)

    return cleaned


def _reject_unknown(container: str, keys: set[str], allowed: frozenset[str]) -> None:
    unknown = sorted(keys - allowed)
    if unknown:
        raise TenantSettingsContractError(
            f"Unsupported {container} key(s): {', '.join(unknown)}."
        )


def _require_bool_map(value: Any, field_name: str) -> dict:
    if not isinstance(value, dict):
        raise TenantSettingsContractError(f"{field_name} must be a JSON object.")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise TenantSettingsContractError(
                f"{field_name} keys must be non-empty strings."
            )
        if not isinstance(item, bool):
            raise TenantSettingsContractError(
                f"{field_name}.{key} must be a boolean."
            )
    return value


def _require_string_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise TenantSettingsContractError(f"{field_name} must be a list of strings.")
    for item in value:
        if not isinstance(item, str):
            raise TenantSettingsContractError(f"{field_name} must contain only strings.")


def _validate_theme(theme: Any) -> None:
    if theme is None:
        return
    if not isinstance(theme, dict):
        raise TenantSettingsContractError("theme must be a JSON object.")
    try:
        validate_tenant_branding(theme)
    except ValueError as exc:
        raise TenantSettingsContractError(str(exc)) from exc
    _reject_unknown("theme", set(theme.keys()), THEME_ALLOWED_KEYS)


def _validate_marketplace(marketplace: Any) -> None:
    if marketplace is None:
        return
    if not isinstance(marketplace, dict):
        raise TenantSettingsContractError("marketplace must be a JSON object.")
    _reject_unknown("marketplace", set(marketplace.keys()), MARKETPLACE_ALLOWED_KEYS)

    if "tagline" in marketplace and not isinstance(marketplace["tagline"], str):
        raise TenantSettingsContractError("marketplace.tagline must be a string.")
    if "story" in marketplace and not isinstance(marketplace["story"], str):
        raise TenantSettingsContractError("marketplace.story must be a string.")
    if "website" in marketplace and not isinstance(marketplace["website"], str):
        raise TenantSettingsContractError("marketplace.website must be a string.")
    if "heroImage" in marketplace and not isinstance(marketplace["heroImage"], str):
        raise TenantSettingsContractError("marketplace.heroImage must be a string.")
    for flag_key in ("featured", "popular", "isNew"):
        if flag_key in marketplace and not isinstance(marketplace[flag_key], bool):
            raise TenantSettingsContractError(
                f"marketplace.{flag_key} must be a boolean."
            )
    if "priceLevel" in marketplace:
        level = marketplace["priceLevel"]
        if not isinstance(level, int) or isinstance(level, bool) or level not in (1, 2, 3, 4):
            raise TenantSettingsContractError(
                "marketplace.priceLevel must be an integer from 1 to 4."
            )
    if "tags" in marketplace:
        _require_string_list(marketplace["tags"], "marketplace.tags")
    if "gallery" in marketplace:
        _require_string_list(marketplace["gallery"], "marketplace.gallery")
    if "rating" in marketplace:
        rating = marketplace["rating"]
        if isinstance(rating, bool) or not isinstance(rating, (int, float)):
            raise TenantSettingsContractError("marketplace.rating must be a number.")
    if "reviewCount" in marketplace:
        count = marketplace["reviewCount"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise TenantSettingsContractError(
                "marketplace.reviewCount must be a non-negative integer."
            )
    if "socialLinks" in marketplace:
        links = marketplace["socialLinks"]
        if not isinstance(links, dict):
            raise TenantSettingsContractError("marketplace.socialLinks must be a JSON object.")
        _reject_unknown("marketplace.socialLinks", set(links.keys()), SOCIAL_LINKS_ALLOWED_KEYS)
        for key, url in links.items():
            if url is not None and not isinstance(url, str):
                raise TenantSettingsContractError(
                    f"marketplace.socialLinks.{key} must be a string."
                )


def _validate_notification_matrix(matrix: Any) -> None:
    if matrix is None:
        return
    if not isinstance(matrix, dict):
        raise TenantSettingsContractError("notificationMatrix must be a JSON object.")
    for event, channels in matrix.items():
        if not isinstance(event, str) or not event:
            raise TenantSettingsContractError(
                "notificationMatrix keys must be non-empty strings."
            )
        if not isinstance(channels, dict):
            raise TenantSettingsContractError(
                f"notificationMatrix[{event!r}] must be a JSON object."
            )
        for channel, enabled in channels.items():
            if not isinstance(channel, str) or not channel:
                raise TenantSettingsContractError(
                    "notificationMatrix channel keys must be non-empty strings."
                )
            if not isinstance(enabled, bool):
                raise TenantSettingsContractError(
                    f"notificationMatrix[{event!r}].{channel} must be a boolean."
                )


def validate_tenant_settings_contract(settings: Any) -> dict:
    """Strip deprecated keys, then reject unknown/malformed remaining keys.

    Used for API create/update/settings-patch. Does not mutate stored extras
    that never pass through an API serializer.
    """
    cleaned = strip_deprecated_tenant_settings(settings)
    _reject_unknown("settings", set(cleaned.keys()), ALLOWED_TOP_LEVEL_KEYS)

    if "theme" in cleaned:
        _validate_theme(cleaned["theme"])
    if "featureFlags" in cleaned:
        _require_bool_map(cleaned["featureFlags"], "featureFlags")
    if "addressCapabilities" in cleaned:
        _require_bool_map(cleaned["addressCapabilities"], "addressCapabilities")
    if "marketplace" in cleaned:
        _validate_marketplace(cleaned["marketplace"])
    if "contactEmail" in cleaned and not isinstance(cleaned["contactEmail"], str):
        raise TenantSettingsContractError("contactEmail must be a string.")
    if "contactPhone" in cleaned and not isinstance(cleaned["contactPhone"], str):
        raise TenantSettingsContractError("contactPhone must be a string.")
    if "notificationMatrix" in cleaned:
        _validate_notification_matrix(cleaned["notificationMatrix"])

    return cleaned


def _project_settings(settings: Any, keys: frozenset[str]) -> dict:
    cleaned = strip_deprecated_tenant_settings(settings)
    projected: dict[str, Any] = {}
    for key in keys:
        if key not in cleaned:
            continue
        if key == "marketplace" and isinstance(cleaned["marketplace"], dict):
            projected["marketplace"] = {
                nested_key: value
                for nested_key, value in cleaned["marketplace"].items()
                if nested_key in MARKETPLACE_ALLOWED_KEYS
            }
        else:
            projected[key] = cleaned[key]
    return projected


def project_public_tenant_settings(settings: Any) -> dict:
    """Settings safe for public tenant list/retrieve (not a raw dump)."""
    return _project_settings(settings, PUBLIC_SETTINGS_KEYS)


def project_owner_tenant_settings(settings: Any) -> dict:
    """Console/owner settings: canonical allowlist, including internal keys.

    Includes ``addressCapabilities`` and ``notificationMatrix``. Omits
    stored extras and deprecated keys so authenticated responses cannot
    echo an arbitrary JSON blob. Database extras are still preserved on
    ``save()`` / settings patch merge.
    """
    return _project_settings(settings, ALLOWED_TOP_LEVEL_KEYS)


def merge_settings_patch(existing: Any, patch: Any) -> dict:
    """Top-level merge. Validates the patch only so stored extras are preserved."""
    if not isinstance(patch, dict):
        raise TenantSettingsContractError("settings patch must be a JSON object.")
    validated_patch = validate_tenant_settings_contract(patch)
    merged = strip_deprecated_tenant_settings(existing)
    merged.update(validated_patch)
    return merged


# Backward-compatible name used by Phase 1 call sites.
strip_phase1_deprecated_tenant_settings = strip_deprecated_tenant_settings
