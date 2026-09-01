"""Strip duplicated/computed keys from Tenant.settings.

Phase 1: locale, ordering, features.reservations, marketplace
cuisines/amenities/openNow/branchCount/primaryBranchSlug.

Phase 2: marketplace fields whose operational source of truth is Branch
(city, email, phone_number, description, coverImage) plus the legacy
marketplace.branches JSON list (derived from Branch records).

Write policy: strip (do not reject, do not copy onto Branch).
Listing-only keys (tagline, tags, featured, priceLevel, gallery, rating,
reviewCount) are left in settings until a later product decision.
"""
from __future__ import annotations

from typing import Any

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

    features = cleaned.get("features")
    if isinstance(features, dict):
        features = dict(features)
        features.pop("reservations", None)
        if features:
            cleaned["features"] = features
        else:
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


# Backward-compatible name used by Phase 1 call sites.
strip_phase1_deprecated_tenant_settings = strip_deprecated_tenant_settings
