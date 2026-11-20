"""Branch service area + pin verification rules (frontend Phase L1/L2 contract).

Pure functions — no ORM, no request objects — so they are trivial to test and
safe to use from serializers, business-logic and cache builders.

Service area (JSON on ``Branch.service_area``), camelCase like the API::

    {
      "mode": "delivery" | "on_site" | "visit_only",
      "shape": {"type": "circle", "radiusKm": 6}
             | {"type": "polygon", "points": [{"lat": .., "lng": ..}, ...]},
      "zones": [{"upToKm": 3, "fee": 0, "etaMinutes": 30}, ...]      # optional
    }

``None`` means "no custom area": clients fall back to the delivery radius and
then the business-type default.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

SERVICE_AREA_MODES = ("delivery", "on_site", "visit_only")
MAX_RADIUS_KM = 500
MIN_POLYGON_POINTS = 3
MAX_POLYGON_POINTS = 200
MAX_ZONES = 20

# Discover payload bounds (keeps the public listing small and predictable).
MAX_MENU_NAMES_PER_BRANCH = 300


class ServiceAreaError(ValueError):
    """Raised with a client-safe message when a service area is invalid."""


def _number(value: Any, label: str) -> float:
    # bool is an int subclass — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ServiceAreaError(f"{label} must be a number.")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ServiceAreaError(f"{label} must be a finite number.")
    return number


def _point(raw: Any, index: int) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ServiceAreaError(f"shape.points[{index}] must be an object with lat and lng.")
    lat = _number(raw.get("lat"), f"shape.points[{index}].lat")
    lng = _number(raw.get("lng"), f"shape.points[{index}].lng")
    if not -90 <= lat <= 90:
        raise ServiceAreaError(f"shape.points[{index}].lat must be between -90 and 90.")
    if not -180 <= lng <= 180:
        raise ServiceAreaError(f"shape.points[{index}].lng must be between -180 and 180.")
    if lat == 0 and lng == 0:
        raise ServiceAreaError(f"shape.points[{index}] must not be 0,0.")
    return {"lat": lat, "lng": lng}


def validate_service_area(value: Any) -> dict[str, Any] | None:
    """Validate and normalise a service area; ``None`` clears it.

    Unknown keys are dropped so the stored JSON stays within the contract.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ServiceAreaError("serviceArea must be an object or null.")

    mode = value.get("mode")
    if mode not in SERVICE_AREA_MODES:
        raise ServiceAreaError(
            f"serviceArea.mode must be one of: {', '.join(SERVICE_AREA_MODES)}."
        )

    shape = value.get("shape")
    if not isinstance(shape, dict):
        raise ServiceAreaError("serviceArea.shape is required.")

    shape_type = shape.get("type")
    radius_km: float | None = None
    if shape_type == "circle":
        radius_km = _number(shape.get("radiusKm"), "shape.radiusKm")
        if not 0 < radius_km <= MAX_RADIUS_KM:
            raise ServiceAreaError(
                f"shape.radiusKm must be greater than 0 and at most {MAX_RADIUS_KM}."
            )
        clean_shape: dict[str, Any] = {"type": "circle", "radiusKm": radius_km}
    elif shape_type == "polygon":
        points = shape.get("points")
        if not isinstance(points, list):
            raise ServiceAreaError("shape.points must be a list.")
        if not MIN_POLYGON_POINTS <= len(points) <= MAX_POLYGON_POINTS:
            raise ServiceAreaError(
                f"shape.points must have between {MIN_POLYGON_POINTS} and {MAX_POLYGON_POINTS} points."
            )
        clean_shape = {
            "type": "polygon",
            "points": [_point(raw, i) for i, raw in enumerate(points)],
        }
    else:
        raise ServiceAreaError("shape.type must be 'circle' or 'polygon'.")

    result: dict[str, Any] = {"mode": mode, "shape": clean_shape}

    zones = value.get("zones")
    if zones is not None:
        if not isinstance(zones, list) or len(zones) > MAX_ZONES:
            raise ServiceAreaError(f"zones must be a list of at most {MAX_ZONES} entries.")
        clean_zones: list[dict[str, Any]] = []
        previous_limit = 0.0
        for i, raw in enumerate(zones):
            if not isinstance(raw, dict):
                raise ServiceAreaError(f"zones[{i}] must be an object.")
            up_to = _number(raw.get("upToKm"), f"zones[{i}].upToKm")
            if up_to <= previous_limit:
                raise ServiceAreaError("zones[].upToKm must be positive and strictly ascending.")
            if radius_km is not None and up_to > radius_km:
                raise ServiceAreaError("zones[].upToKm must not exceed shape.radiusKm.")
            zone: dict[str, Any] = {"upToKm": up_to}
            if raw.get("fee") is not None:
                fee = _number(raw["fee"], f"zones[{i}].fee")
                if fee < 0:
                    raise ServiceAreaError(f"zones[{i}].fee must not be negative.")
                zone["fee"] = fee
            if raw.get("etaMinutes") is not None:
                eta = _number(raw["etaMinutes"], f"zones[{i}].etaMinutes")
                if eta < 0:
                    raise ServiceAreaError(f"zones[{i}].etaMinutes must not be negative.")
                zone["etaMinutes"] = eta
            previous_limit = up_to
            clean_zones.append(zone)
        if clean_zones:
            result["zones"] = clean_zones

    return result


def _same_instant(a: datetime | None, b: datetime | None) -> bool:
    """Equal to the second — clients round-trip ISO strings and lose microseconds."""
    if a is None or b is None:
        return False
    return a.replace(microsecond=0) == b.replace(microsecond=0)


def resolve_location_verified_at(
    *,
    stored: datetime | None,
    provided: bool,
    incoming: datetime | None,
    coordinates_changed: bool,
    now: datetime,
) -> datetime | None:
    """Decide the stored ``location_verified_at`` for a branch write.

    Rules (from the L2 contract):
      * the stored value is always **server time** — a client clock is never trusted;
      * a client ``null`` clears it;
      * a client value that equals what is already stored is just the form
        echoing the old value back: keep it, unless the pin moved in the same
        request (then the old confirmation no longer applies);
      * any other non-null client value is a fresh owner confirmation → ``now``;
      * if the pin moved and the request carried no confirmation, it resets.
    """
    if provided:
        if incoming is None:
            return None
        if _same_instant(incoming, stored):
            return None if coordinates_changed else stored
        return now
    return None if coordinates_changed else stored
