from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from addresses.domain.geospatial import GeoPoint, GeoStorage
from tenants.selectors.tenant_availability import tenant_is_operationally_available


@dataclass(frozen=True)
class DeliveryZoneResult:
    branch_id: UUID
    branch_name: str
    branch_status: str
    available: bool
    serviceable: bool
    distance_km: float | None
    delivery_fee: Decimal
    estimated_delivery_time: int | None
    minimum_order: Decimal
    currency: str
    zone_name: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ServiceabilityResult:
    serviceable: bool
    delivery_zone: str | None
    assigned_branch: dict[str, Any]
    delivery_fee: Decimal
    estimated_delivery_time: int | None
    distance: float | None
    minimum_order: Decimal
    currency: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "serviceable": self.serviceable,
            "delivery_zone": self.delivery_zone,
            "assigned_branch": self.assigned_branch,
            "delivery_fee": str(self.delivery_fee),
            "estimated_delivery_time": self.estimated_delivery_time,
            "distance": self.distance,
            "minimum_order": str(self.minimum_order),
            "currency": self.currency,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BranchResolutionResult:
    branch_id: UUID
    branch_name: str
    branch_status: str
    distance: float | None
    delivery_radius: float | None
    estimated_delivery_time: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.branch_id),
            "name": self.branch_name,
            "status": self.branch_status,
            "distance": self.distance,
            "delivery_radius": self.delivery_radius,
            "estimated_delivery_time": self.estimated_delivery_time,
        }


class DeliveryZoneService:
    """
    Resolves delivery availability, fee, ETA, and distance for a branch/address pair.
    Uses typed Branch checkout columns.
    """

    BASE_FEE = Decimal("2.50")
    PER_KM_FEE = Decimal("0.75")
    BASE_ETA_MINUTES = 25
    PER_KM_ETA_MINUTES = 3
    DEFAULT_MINIMUM_ORDER = Decimal("0.00")
    DEFAULT_CURRENCY = "USD"

    def _minimum_order(self, branch) -> Decimal:
        raw = branch.minimum_order_amount
        if raw is None:
            return self.DEFAULT_MINIMUM_ORDER
        return Decimal(str(raw)).quantize(Decimal("0.01"))

    def _currency(self, branch) -> str:
        return getattr(branch, "currency", None) or self.DEFAULT_CURRENCY

    def _delivery_radius(self, branch) -> float | None:
        raw = branch.delivery_radius_km
        return float(raw) if raw is not None else None

    def resolve(self, *, branch, destination: GeoPoint | None) -> DeliveryZoneResult:
        delivery_enabled = bool(branch.delivery_enabled)
        radius_km = branch.delivery_radius_km

        tenant = getattr(branch, "tenant", None)
        minimum_order = self._minimum_order(branch)
        currency = self._currency(branch)
        branch_status = getattr(branch, "status", "active")

        if tenant is not None and not tenant_is_operationally_available(tenant):
            return DeliveryZoneResult(
                branch_id=branch.id,
                branch_name=branch.name or "",
                branch_status=branch_status,
                available=False,
                serviceable=False,
                distance_km=None,
                delivery_fee=Decimal("0.00"),
                estimated_delivery_time=None,
                minimum_order=minimum_order,
                currency=currency,
                zone_name=None,
                reason="This business is not currently available for delivery.",
            )

        branch_point = GeoStorage.from_model(branch)
        distance_km = None
        if branch_point and destination:
            distance_km = round(GeoStorage.distance_km(branch_point, destination), 2)

        if not delivery_enabled:
            return DeliveryZoneResult(
                branch_id=branch.id,
                branch_name=branch.name or "",
                branch_status=branch_status,
                available=False,
                serviceable=False,
                distance_km=distance_km,
                delivery_fee=Decimal("0.00"),
                estimated_delivery_time=None,
                minimum_order=minimum_order,
                currency=currency,
                zone_name=None,
                reason="Delivery is not enabled for this branch.",
            )

        if destination is None:
            return DeliveryZoneResult(
                branch_id=branch.id,
                branch_name=branch.name or "",
                branch_status=branch_status,
                available=True,
                serviceable=False,
                distance_km=None,
                delivery_fee=self.BASE_FEE,
                estimated_delivery_time=self.BASE_ETA_MINUTES,
                minimum_order=minimum_order,
                currency=currency,
                zone_name="unknown",
                reason="Coordinates required to confirm serviceability.",
            )

        serviceable = True
        reason = None
        if radius_km is not None and distance_km is not None:
            serviceable = distance_km <= float(radius_km)
            if not serviceable:
                reason = f"Address is outside the {radius_km} km delivery radius."

        fee = self.BASE_FEE
        eta = self.BASE_ETA_MINUTES
        if distance_km is not None:
            fee += Decimal(str(distance_km)) * self.PER_KM_FEE
            eta += int(distance_km * self.PER_KM_ETA_MINUTES)

        return DeliveryZoneResult(
            branch_id=branch.id,
            branch_name=branch.name or "",
            branch_status=branch_status,
            available=True,
            serviceable=serviceable,
            distance_km=distance_km,
            delivery_fee=fee.quantize(Decimal("0.01")),
            estimated_delivery_time=eta,
            minimum_order=minimum_order,
            currency=currency,
            zone_name=f"branch:{branch.id}",
            reason=reason,
        )

    def resolve_from_data(self, *, branch, data: dict[str, Any]) -> DeliveryZoneResult:
        lat = data.get("latitude") if data.get("latitude") is not None else data.get("lat")
        lng = data.get("longitude") if data.get("longitude") is not None else data.get("lng")
        point = GeoPoint(float(lat), float(lng)) if lat is not None and lng is not None else None
        return self.resolve(branch=branch, destination=point)

    def to_serviceability(self, zone: DeliveryZoneResult) -> ServiceabilityResult:
        return ServiceabilityResult(
            serviceable=zone.serviceable and zone.available,
            delivery_zone=zone.zone_name,
            assigned_branch={"id": str(zone.branch_id), "name": zone.branch_name},
            delivery_fee=zone.delivery_fee,
            estimated_delivery_time=zone.estimated_delivery_time,
            distance=zone.distance_km,
            minimum_order=zone.minimum_order,
            currency=zone.currency,
            reason=zone.reason,
        )

    def to_branch_resolution(self, zone: DeliveryZoneResult, *, branch) -> BranchResolutionResult:
        return BranchResolutionResult(
            branch_id=zone.branch_id,
            branch_name=zone.branch_name,
            branch_status=zone.branch_status,
            distance=zone.distance_km,
            delivery_radius=self._delivery_radius(branch),
            estimated_delivery_time=zone.estimated_delivery_time,
        )
