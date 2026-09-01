"""Strip Phase 1 duplicated keys from Tenant.settings.

These keys already have a typed source of truth on Branch, or are
computed at read time. Tenant.settings must not remain a second copy.

Write policy: strip (do not reject, do not copy onto Branch). This matches
the Branch.settings operational-key strip and avoids 400s for clients
still sending the old bag.
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


def strip_phase1_deprecated_tenant_settings(settings: Any) -> dict:
    """Return a copy of settings with Phase 1 duplicated/computed keys removed."""
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
            if key not in PHASE1_MARKETPLACE_KEYS
        }
        if marketplace:
            cleaned["marketplace"] = marketplace
        else:
            cleaned.pop("marketplace", None)

    return cleaned
