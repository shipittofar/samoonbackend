from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from addresses.domain.geospatial import GeoPoint


@dataclass
class GeocodeResult:
    point: GeoPoint
    provider: str
    confidence: float = 1.0
    formatted_address: str = ""


@dataclass
class SuggestionResult:
    formatted_address: str
    latitude: float
    longitude: float
    provider: str
    confidence: float = 0.0


class GeocoderProvider(ABC):
    name: str

    @abstractmethod
    def geocode(self, *, street: str, city: str, country: str, postal_code: str = "") -> GeocodeResult | None:
        ...

    def suggest(
        self,
        *,
        query: str,
        country: str = "",
        city: str = "",
        language: str = "",
    ) -> list[SuggestionResult]:
        return []


class NoopGeocoderProvider(GeocoderProvider):
    """Default provider — returns empty; swap via settings without API changes."""

    name = "noop"

    def geocode(self, *, street: str, city: str, country: str, postal_code: str = "") -> GeocodeResult | None:
        return None

    def suggest(self, *, query: str, country: str = "", city: str = "", language: str = "") -> list[SuggestionResult]:
        return []


class GeocoderService:
    def __init__(self, provider: GeocoderProvider | None = None):
        self.provider = provider or NoopGeocoderProvider()

    def geocode_address(self, data: dict) -> GeocodeResult | None:
        return self.provider.geocode(
            street=data.get("street", ""),
            city=data.get("city", ""),
            country=data.get("country", ""),
            postal_code=data.get("postal_code", ""),
        )

    def suggest_addresses(
        self,
        *,
        query: str,
        country: str = "",
        city: str = "",
        language: str = "",
    ) -> list[SuggestionResult]:
        if not query or not query.strip():
            return []
        return self.provider.suggest(
            query=query.strip(),
            country=country.strip().upper() if country else "",
            city=city.strip(),
            language=language.strip().lower() if language else "",
        )
