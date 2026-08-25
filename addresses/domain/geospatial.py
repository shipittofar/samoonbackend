from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float


class GeoStorage:
    """
    Geospatial abstraction. Uses plain lat/lng today; can be swapped for
    PostGIS PointField without changing callers or API contracts.
    """

    @staticmethod
    def has_postgis() -> bool:
        try:
            from django.contrib.gis.geos import Point  # noqa: F401
            return "django.contrib.gis" in __import__("django.conf", fromlist=["settings"]).settings.INSTALLED_APPS
        except ImportError:
            return False

    @staticmethod
    def from_model(obj: Any) -> GeoPoint | None:
        lat = getattr(obj, "latitude", None)
        lng = getattr(obj, "longitude", None)
        if lat is None or lng is None:
            return None
        return GeoPoint(latitude=float(lat), longitude=float(lng))

    @staticmethod
    def apply_to_dict(data: dict, point: GeoPoint | None) -> dict:
        if point is None:
            data["latitude"] = None
            data["longitude"] = None
        else:
            data["latitude"] = point.latitude
            data["longitude"] = point.longitude
        return data

    @staticmethod
    def distance_km(a: GeoPoint, b: GeoPoint) -> float:
        """Haversine distance in kilometres."""
        radius = 6371.0
        lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
        lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * radius * math.asin(math.sqrt(h))
