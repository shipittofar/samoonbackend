"""
Cache-safe DTO payloads for tenant/branch reads.

Cached values are plain dicts (via ``dataclasses.asdict``). Callers of
``get_*`` receive these DTO instances — never ORM models. Write paths must
use ``*_for_update`` helpers that always hit the database.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID


def _image_name(file_field) -> str | None:
    if not file_field:
        return None
    name = getattr(file_field, "name", None) or str(file_field)
    return name or None


def _image_url(file_field) -> str | None:
    if not file_field:
        return None
    try:
        return file_field.url
    except (ValueError, AttributeError):
        return None


@dataclass(slots=True)
class WorkingHourDTO:
    """Flat working-hour row for branch detail / discover availability."""

    day: int
    open_time: time | None
    close_time: time | None
    is_closed: bool

    @classmethod
    def from_model(cls, wh) -> WorkingHourDTO:
        return cls(
            day=wh.day,
            open_time=wh.open_time,
            close_time=wh.close_time,
            is_closed=wh.is_closed,
        )


@dataclass(slots=True)
class TenantDTO:
    """
    Cached tenant read model.

    ``owner_user_id`` is intentionally flat so ownership checks never need
    ``tenant.owner`` / ``tenant.owner.user`` relation traversal.
    ``owner_id`` is the Owner PK (useful for uniqueness checks on writes
    that already hold a DTO from a prior read — write paths still use
    ``*_for_update`` for mutation).
    """

    id: UUID
    owner_id: UUID
    owner_user_id: UUID
    name: str
    slug: str
    tax_percentage: Decimal
    service_charge_percentage: Decimal
    image: str | None
    image_url: str | None
    discover_avatar: str | None
    discover_avatar_url: str | None
    discover_cover: str | None
    discover_cover_url: str | None
    hero_image: str | None
    hero_image_url: str | None
    business_types: list
    status: str
    is_active: bool
    # Full stored JSON for cache/merge. HTTP serializers project, they do not dump this.
    settings: dict
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, tenant) -> TenantDTO:
        owner = tenant.owner
        return cls(
            id=tenant.id,
            owner_id=tenant.owner_id,
            owner_user_id=owner.user_id,
            name=tenant.name,
            slug=tenant.slug,
            tax_percentage=tenant.tax_percentage,
            service_charge_percentage=tenant.service_charge_percentage,
            image=_image_name(tenant.image),
            image_url=_image_url(tenant.image),
            discover_avatar=_image_name(tenant.discover_avatar),
            discover_avatar_url=_image_url(tenant.discover_avatar),
            discover_cover=_image_name(tenant.discover_cover),
            discover_cover_url=_image_url(tenant.discover_cover),
            hero_image=_image_name(tenant.hero_image),
            hero_image_url=_image_url(tenant.hero_image),
            business_types=list(tenant.business_types or []),
            status=tenant.status,
            is_active=tenant.is_active,
            settings=dict(tenant.settings or {}),
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )

    def to_cache_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> TenantDTO:
        payload = dict(data)
        payload.setdefault("is_active", False)
        payload.setdefault("discover_avatar", None)
        payload.setdefault("discover_avatar_url", None)
        payload.setdefault("discover_cover", None)
        payload.setdefault("discover_cover_url", None)
        payload.setdefault("hero_image", None)
        payload.setdefault("hero_image_url", None)
        return cls(**payload)


@dataclass(slots=True)
class BranchDTO:
    """
    Cached branch read model.

    ``tenant_id`` is flat for ownership / FK checks without ``branch.tenant``.
    ``owner_user_id`` is denormalized so ``_assert_owns_branch`` can verify
    ownership without a second tenant fetch when the DTO is already loaded.
    """

    id: UUID
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    tenant_is_active: bool
    tenant_status: str
    owner_user_id: UUID | None
    name: str
    slug: str
    description: str
    type: str
    manager_id: UUID | None
    phone: str
    email: str
    website: str
    address: str
    city: str
    country: str
    postal_code: str
    latitude: Decimal | None
    longitude: Decimal | None
    image: str | None
    image_url: str | None
    cover_image: str | None
    cover_image_url: str | None
    hero_image: str | None
    hero_image_url: str | None
    time_zone: str
    currency: str
    language: str
    ordering_enabled: bool
    delivery_enabled: bool
    pickup_enabled: bool
    table_ordering_enabled: bool
    default_order_type: str | None
    delivery_radius_km: int | None
    minimum_order_amount: Decimal | None
    same_day_delivery_enabled: bool
    scheduled_delivery_enabled: bool
    contactless_delivery_enabled: bool
    cash_on_delivery_enabled: bool
    cash_payment_enabled: bool
    card_payment_enabled: bool
    online_payment_enabled: bool
    wallet_payment_enabled: bool
    default_payment_method: str | None
    marketplace_visible: bool
    reservations_enabled: bool
    max_capacity: int | None
    cuisines: list
    amenities: list
    settings: dict
    metadata: dict
    status: str
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime
    working_hours: list[WorkingHourDTO] = field(default_factory=list)

    @classmethod
    def from_model(cls, branch) -> BranchDTO:
        owner_user_id = None
        tenant = getattr(branch, "tenant", None)
        if tenant is not None and getattr(tenant, "owner_id", None):
            owner = getattr(tenant, "owner", None)
            if owner is not None:
                owner_user_id = owner.user_id
        hours = [
            WorkingHourDTO.from_model(wh)
            for wh in branch.working_hours.all()
        ]
        return cls(
            id=branch.id,
            tenant_id=branch.tenant_id,
            tenant_name=tenant.name if tenant is not None else "",
            tenant_slug=tenant.slug if tenant is not None else "",
            tenant_is_active=tenant.is_active if tenant is not None else False,
            tenant_status=tenant.status if tenant is not None else "inactive",
            owner_user_id=owner_user_id,
            name=branch.name,
            slug=branch.slug,
            description=branch.description or "",
            type=branch.type,
            manager_id=branch.manager_id,
            phone=branch.phone or "",
            email=branch.email or "",
            website=branch.website or "",
            address=branch.address or "",
            city=branch.city or "",
            country=branch.country or "",
            postal_code=branch.postal_code or "",
            latitude=branch.latitude,
            longitude=branch.longitude,
            image=_image_name(branch.image),
            image_url=_image_url(branch.image),
            cover_image=_image_name(branch.cover_image),
            cover_image_url=_image_url(branch.cover_image),
            hero_image=_image_name(branch.hero_image),
            hero_image_url=_image_url(branch.hero_image),
            time_zone=branch.time_zone or "UTC",
            currency=branch.currency or "USD",
            language=branch.language or "en",
            ordering_enabled=branch.ordering_enabled,
            delivery_enabled=branch.delivery_enabled,
            pickup_enabled=branch.pickup_enabled,
            table_ordering_enabled=branch.table_ordering_enabled,
            default_order_type=branch.default_order_type,
            delivery_radius_km=branch.delivery_radius_km,
            minimum_order_amount=branch.minimum_order_amount,
            same_day_delivery_enabled=branch.same_day_delivery_enabled,
            scheduled_delivery_enabled=branch.scheduled_delivery_enabled,
            contactless_delivery_enabled=branch.contactless_delivery_enabled,
            cash_on_delivery_enabled=branch.cash_on_delivery_enabled,
            cash_payment_enabled=branch.cash_payment_enabled,
            card_payment_enabled=branch.card_payment_enabled,
            online_payment_enabled=branch.online_payment_enabled,
            wallet_payment_enabled=branch.wallet_payment_enabled,
            default_payment_method=branch.default_payment_method,
            marketplace_visible=branch.marketplace_visible,
            reservations_enabled=branch.reservations_enabled,
            max_capacity=branch.max_capacity,
            cuisines=list(branch.cuisines or []),
            amenities=list(branch.amenities or []),
            settings=dict(branch.settings or {}),
            metadata=dict(branch.metadata or {}),
            status=branch.status,
            is_active=branch.is_active,
            is_default=branch.is_default,
            created_at=branch.created_at,
            updated_at=branch.updated_at,
            working_hours=hours,
        )

    def to_cache_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> BranchDTO:
        hours_raw = data.get("working_hours") or []
        hours = [
            h if isinstance(h, WorkingHourDTO) else WorkingHourDTO(**h)
            for h in hours_raw
        ]
        payload = dict(data)
        payload["working_hours"] = hours
        payload.setdefault("tenant_name", "")
        payload.setdefault("tenant_slug", "")
        payload.setdefault("tenant_is_active", False)
        payload.setdefault("tenant_status", "inactive")
        payload.setdefault("cuisines", [])
        payload.setdefault("amenities", [])
        payload.setdefault("hero_image", None)
        payload.setdefault("hero_image_url", None)
        return cls(**payload)


@dataclass(slots=True)
class BranchDiscoverDTO:
    """
    Nested branch shape for GET /api/public/discover/.

    Fields match ``DiscoverBranchResponseSerializer`` (+ flat ids and the
    working-hour rows needed to compute ``openNow`` / ``todayHours`` at
    request time without ORM).
    """

    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    image: str | None
    image_url: str | None
    address: str
    city: str
    country: str
    is_active: bool
    status: str
    is_default: bool
    time_zone: str
    email: str = ""
    phone: str = ""
    description: str = ""
    cover_image: str | None = None
    cover_image_url: str | None = None
    hero_image: str | None = None
    hero_image_url: str | None = None
    cuisines: list = field(default_factory=list)
    amenities: list = field(default_factory=list)
    working_hours: list[WorkingHourDTO] = field(default_factory=list)

    @classmethod
    def from_model(cls, branch) -> BranchDiscoverDTO:
        return cls(
            id=branch.id,
            tenant_id=branch.tenant_id,
            slug=branch.slug,
            name=branch.name,
            image=_image_name(branch.image),
            image_url=_image_url(branch.image),
            address=branch.address or "",
            city=branch.city or "",
            country=branch.country or "",
            is_active=branch.is_active,
            status=branch.status,
            is_default=branch.is_default,
            time_zone=branch.time_zone or "UTC",
            email=branch.email or "",
            phone=branch.phone or "",
            description=branch.description or "",
            cover_image=_image_name(branch.cover_image),
            cover_image_url=_image_url(branch.cover_image),
            hero_image=_image_name(branch.hero_image),
            hero_image_url=_image_url(branch.hero_image),
            cuisines=list(branch.cuisines or []),
            amenities=list(branch.amenities or []),
            working_hours=[
                WorkingHourDTO.from_model(wh) for wh in branch.working_hours.all()
            ],
        )

    def to_cache_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> BranchDiscoverDTO:
        hours_raw = data.get("working_hours") or []
        hours = [
            h if isinstance(h, WorkingHourDTO) else WorkingHourDTO(**h)
            for h in hours_raw
        ]
        payload = dict(data)
        payload["working_hours"] = hours
        payload.setdefault("cuisines", [])
        payload.setdefault("amenities", [])
        payload.setdefault("email", "")
        payload.setdefault("phone", "")
        payload.setdefault("description", "")
        payload.setdefault("cover_image", None)
        payload.setdefault("cover_image_url", None)
        payload.setdefault("hero_image", None)
        payload.setdefault("hero_image_url", None)
        return cls(**payload)


@dataclass(slots=True)
class TenantDiscoverDTO:
    """
    Cached discover-list tenant row.

    Matches ``DiscoverTenantResponseSerializer`` inputs: identity fields,
    settings (featureFlags / theme / marketplace source; full blob cached),
    and nested public branches as ``BranchDiscoverDTO``. Discover responses
    never dump the settings object.
    """

    id: UUID
    slug: str
    name: str
    is_active: bool
    status: str
    created_at: datetime
    business_types: list
    settings: dict
    image: str | None
    image_url: str | None
    discover_avatar: str | None = None
    discover_avatar_url: str | None = None
    discover_cover: str | None = None
    discover_cover_url: str | None = None
    hero_image: str | None = None
    hero_image_url: str | None = None
    branches: list[BranchDiscoverDTO] = field(default_factory=list)

    @classmethod
    def from_model(cls, tenant) -> TenantDiscoverDTO:
        return cls(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_active=tenant.is_active,
            status=tenant.status,
            created_at=tenant.created_at,
            business_types=list(tenant.business_types or []),
            settings=dict(tenant.settings or {}),
            image=_image_name(tenant.image),
            image_url=_image_url(tenant.image),
            discover_avatar=_image_name(tenant.discover_avatar),
            discover_avatar_url=_image_url(tenant.discover_avatar),
            discover_cover=_image_name(tenant.discover_cover),
            discover_cover_url=_image_url(tenant.discover_cover),
            hero_image=_image_name(tenant.hero_image),
            hero_image_url=_image_url(tenant.hero_image),
            branches=[
                BranchDiscoverDTO.from_model(branch)
                for branch in tenant.branches.all()
            ],
        )

    def to_cache_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> TenantDiscoverDTO:
        branches_raw = data.get("branches") or []
        branches = [
            b if isinstance(b, BranchDiscoverDTO) else BranchDiscoverDTO.from_cache_dict(b)
            for b in branches_raw
        ]
        payload = dict(data)
        payload["branches"] = branches
        payload.setdefault("image", None)
        payload.setdefault("image_url", None)
        payload.setdefault("discover_avatar", None)
        payload.setdefault("discover_avatar_url", None)
        payload.setdefault("discover_cover", None)
        payload.setdefault("discover_cover_url", None)
        payload.setdefault("hero_image", None)
        payload.setdefault("hero_image_url", None)
        payload.setdefault("is_active", False)
        payload.setdefault("status", "inactive")
        return cls(**payload)
