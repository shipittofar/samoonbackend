from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.api.validators.phone_numbers import validate_country_code, validate_phone_number
from addresses.domain.address_type import display_label, resolve_address_type
from addresses.domain.events import (
    AddressCreated,
    AddressDefaultChanged,
    AddressDeleted,
    AddressEventBus,
    AddressRestored,
    AddressUpdated,
    AddressVerificationChanged,
    DomainEvent,
)
from addresses.domain.formatter import AddressFormatter
from addresses.domain.geocoder import GeocoderService
from addresses.domain.geospatial import GeoPoint, GeoStorage
from addresses.domain.normalizer import AddressNormalizer
from addresses.domain.verification import VerificationStatus
from addresses.models import Address
from addresses.selectors.address_dal import AddressDataAccessLayer
from addresses.selectors.branch_dal import AddressBranchDataAccessLayer
from addresses.services.address_capabilities_service import AddressCapabilitiesService
from addresses.services.audit_service import AddressAuditService
from addresses.services.delivery_zone_service import (
    BranchResolutionResult,
    DeliveryZoneService,
    ServiceabilityResult,
)
from addresses.validators import get_max_user_addresses, validate_coordinates
from core.exceptions import BranchNotFoundException
from core.exceptions.address import (
    AddressLimitExceededException,
    AddressNotFoundException,
    AddressNotServiceableException,
    DuplicateAddressException,
)

CHECKOUT_OVERRIDE_FIELDS = frozenset({
    "delivery_notes", "building_number", "unit", "floor",
})

CLIENT_IDENTITY_FIELDS = frozenset({
    "first_name", "last_name", "country_code", "title", "phone",
})

PROFILE_INCOMPLETE_MESSAGE = "Please complete your profile before creating an address."
PROFILE_PHONE_MISSING_MESSAGE = (
    "Please add a phone number to your profile before creating an address."
)
DEFAULT_COUNTRY_CODE = "+1"
SYSTEM_VERIFICATION_SOURCE = "system"


class AddressDomainService:
    """
    Central domain service for all address business logic.
    Views, serializers, and order services delegate here exclusively.
    """

    def __init__(
        self,
        dal: AddressDataAccessLayer | None = None,
        geocoder: GeocoderService | None = None,
        delivery_zone: DeliveryZoneService | None = None,
        audit: AddressAuditService | None = None,
        capabilities: AddressCapabilitiesService | None = None,
        branch_dal: AddressBranchDataAccessLayer | None = None,
    ):
        self.dal = dal or AddressDataAccessLayer()
        self.geocoder = geocoder or GeocoderService()
        self.delivery_zone = delivery_zone or DeliveryZoneService()
        self.audit = audit or AddressAuditService()
        self.capabilities = capabilities or AddressCapabilitiesService()
        self.branch_dal = branch_dal or AddressBranchDataAccessLayer()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def list_addresses(self, user, *, search: str | None = None, **filters):
        return self.dal.search_for_user(user.id, query=search, **filters)

    def get_address(self, user, address_id) -> Address:
        self.validate_ownership(user, address_id)
        if isinstance(address_id, int):
            address = self.dal.get_for_user_by_legacy_id(address_id, user.id)
        else:
            if isinstance(address_id, str):
                address_id = UUID(address_id)
            address = self.dal.get_for_user(address_id, user.id)
        if address is None:
            raise AddressNotFoundException()
        return address

    def validate_ownership(self, user, address_id) -> None:
        if isinstance(address_id, int):
            exists = self.dal.get_for_user_by_legacy_id(address_id, user.id)
        else:
            if isinstance(address_id, str):
                address_id = UUID(address_id)
            exists = self.dal.get_for_user(address_id, user.id)
        if exists is None:
            raise AddressNotFoundException()

    # ------------------------------------------------------------------
    # Normalize / Validate / Format
    # ------------------------------------------------------------------
    def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        return AddressNormalizer.normalize_payload(data)

    def strip_client_identity_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Remove identity fields supplied by the client; never trust request body."""
        return {key: value for key, value in data.items() if key not in CLIENT_IDENTITY_FIELDS}

    def _extract_user_phone(self, user) -> str:
        raw = getattr(user, "phone_number", None) or ""
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if not digits:
            return ""
        country_code = getattr(user, "country_code", None) or ""
        cc_digits = "".join(ch for ch in str(country_code) if ch.isdigit())
        if cc_digits and digits.startswith(cc_digits):
            local = digits[len(cc_digits):]
        else:
            local = digits[-10:] if len(digits) >= 10 else digits
        if not local:
            return ""
        try:
            return validate_phone_number(local)
        except serializers.ValidationError:
            return ""

    def user_identity(self, user) -> dict[str, str]:
        country_code = getattr(user, "country_code", None) or DEFAULT_COUNTRY_CODE
        try:
            country_code = validate_country_code(country_code)
        except serializers.ValidationError:
            country_code = validate_country_code(DEFAULT_COUNTRY_CODE)
        return {
            "first_name": (getattr(user, "first_name", None) or "").strip(),
            "last_name": (getattr(user, "last_name", None) or "").strip(),
            "country_code": country_code,
            "phone": self._extract_user_phone(user),
        }

    def validate_user_profile(self, user) -> None:
        identity = self.user_identity(user)
        errors: list[str] = []
        if not identity["first_name"] or not identity["last_name"]:
            errors.append(PROFILE_INCOMPLETE_MESSAGE)
        if not identity["phone"]:
            errors.append(PROFILE_PHONE_MISSING_MESSAGE)
        if errors:
            raise serializers.ValidationError({"profile": errors})

    def derive_address_title(self, data: dict[str, Any]) -> str:
        """`title` is the address label (Home, Work, etc.), derived from address_type."""
        address_type = data.get("address_type") or data.get("label") or "home"
        custom_label = data.get("custom_label") or ""
        return display_label(address_type, custom_label)

    def auto_verification_fields(self) -> dict[str, Any]:
        """Default verification applied to every authenticated user address on create."""
        return {
            "verification_status": VerificationStatus.VERIFIED,
            "is_verified": True,
            "verified_at": timezone.now(),
            "verification_source": SYSTEM_VERIFICATION_SOURCE,
        }

    def apply_user_identity(self, user, data: dict[str, Any]) -> dict[str, Any]:
        prepared = self.strip_client_identity_fields(data)
        prepared.update(self.user_identity(user))
        prepared["title"] = self.derive_address_title(prepared)
        return prepared

    def prepare_create(self, user, data: dict[str, Any]) -> dict[str, Any]:
        self.validate_user_profile(user)
        return self.apply_user_identity(user, data)

    def prepare_update(self, user, data: dict[str, Any]) -> dict[str, Any]:
        self.validate_user_profile(user)
        return self.apply_user_identity(user, data)

    def validate(self, data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        normalized = self.normalize(data)
        required = ("country", "city", "street", "postal_code")
        identity_required = ("title", "first_name", "last_name", "country_code", "phone")
        if not partial:
            missing = [field for field in required + identity_required if not normalized.get(field)]
            if missing:
                raise serializers.ValidationError(
                    {field: "This field is required." for field in missing}
                )
        if "country_code" in normalized and normalized["country_code"]:
            normalized["country_code"] = validate_country_code(normalized["country_code"])
        validate_coordinates(normalized.get("latitude"), normalized.get("longitude"))
        if normalized.get("address_type") == "other" and not normalized.get("custom_label") and not partial:
            raise serializers.ValidationError({"custom_label": "Required when address_type is OTHER."})
        return normalized

    def format_address(self, address: Address) -> str:
        return AddressFormatter.format_address(address)

    def compute_fingerprint(self, data: dict[str, Any]) -> str:
        return Address.compute_fingerprint(
            street=data.get("street", ""),
            building_number=data.get("building_number", ""),
            unit=data.get("unit", ""),
            city=data.get("city", ""),
            postal_code=data.get("postal_code", ""),
            country=data.get("country", ""),
        )

    def detect_duplicate(self, user_id: UUID, fingerprint: str, exclude_id: UUID | None = None) -> bool:
        return self.dal.fingerprint_exists(user_id, fingerprint, exclude_id=exclude_id)

    # ------------------------------------------------------------------
    # Serviceability / Branch / Capabilities / Suggestions
    # ------------------------------------------------------------------
    def resolve_branch(self, user, branch_id: UUID | None = None):
        if branch_id is not None:
            branch = self.branch_dal.get_active_branch(branch_id)
        elif getattr(user, "active_branch_id", None):
            branch = self.branch_dal.get_active_branch(user.active_branch_id)
        else:
            raise serializers.ValidationError(
                {"branch_id": "branch_id query parameter or active_branch is required."}
            )
        if branch is None:
            raise BranchNotFoundException()
        return branch

    def _resolve_delivery_data(self, user, delivery_data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        normalized = self.normalize(delivery_data)
        address_id = normalized.get("address_id")

        if address_id is not None:
            book_address = self.get_address(user, address_id)
            data = self._snapshot_from_address(book_address)
            for field in CHECKOUT_OVERRIDE_FIELDS:
                if field in normalized and normalized[field] not in (None, ""):
                    data[field] = normalized[field]
            self.validate_user_profile(user)
            data = self.apply_user_identity(user, data)
        else:
            data = self._snapshot_from_raw(normalized)
            self.validate_user_profile(user)
            data = self.apply_user_identity(user, data)
            self.validate(data, partial=partial)
        data["formatted_address"] = AddressFormatter.format_from_dict(data)
        return data

    def evaluate_serviceability(
        self,
        *,
        user,
        branch,
        delivery_data: dict[str, Any],
    ) -> ServiceabilityResult:
        data = self._resolve_delivery_data(user, delivery_data, partial=True)
        zone = self.delivery_zone.resolve_from_data(branch=branch, data=data)
        return self.delivery_zone.to_serviceability(zone)

    def resolve_branch_for_address(self, *, user, address_id, branch) -> BranchResolutionResult:
        data = self._snapshot_from_address(self.get_address(user, address_id))
        zone = self.delivery_zone.resolve_from_data(branch=branch, data=data)
        return self.delivery_zone.to_branch_resolution(zone, branch=branch)

    def get_capabilities(self, *, user, address: Address, branch) -> dict[str, bool]:
        data = self._snapshot_from_address(address)
        zone = self.delivery_zone.resolve_from_data(branch=branch, data=data)
        return self.capabilities.resolve(branch=branch, tenant=branch.tenant, zone=zone)

    def suggest_addresses(
        self,
        *,
        query: str,
        country: str = "",
        city: str = "",
        language: str = "",
    ) -> list[dict[str, Any]]:
        results = self.geocoder.suggest_addresses(
            query=query, country=country, city=city, language=language
        )
        return [
            {
                "formatted_address": item.formatted_address,
                "latitude": item.latitude,
                "longitude": item.longitude,
                "provider": item.provider,
                "confidence": item.confidence,
            }
            for item in results
        ]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------
    @transaction.atomic
    def create(self, user, data: dict[str, Any], *, actor=None) -> Address:
        prepared = self.prepare_create(user, data)
        validated = self.validate(prepared)
        if self.dal.count_active_for_user(user.id) >= get_max_user_addresses():
            raise AddressLimitExceededException()

        fingerprint = self.compute_fingerprint(validated)
        if self.detect_duplicate(user.id, fingerprint):
            raise DuplicateAddressException()

        validated = self._maybe_geocode(validated)
        validated["formatted_address"] = AddressFormatter.format_from_dict(validated)
        validated["fingerprint"] = fingerprint
        validated.update(self.auto_verification_fields())

        self.dal.lock_user_addresses(user.id)
        is_default = validated.get("is_default", False)
        if is_default or self.dal.count_active_for_user(user.id) == 0:
            validated["is_default"] = True
            self.dal.unset_default_addresses(user.id)

        address = self.dal.create_address(user=user, **self._model_fields(validated))
        self.audit.log(
            address_id=address.id,
            user_id=user.id,
            actor_id=getattr(actor, "id", user.id),
            action=AddressAuditService.ACTION_CREATE,
            changed_fields=validated,
        )
        AddressEventBus.publish(AddressCreated(address.id, user.id))
        return address

    @transaction.atomic
    def update(self, user, address_id: UUID, data: dict[str, Any], *, actor=None) -> Address:
        address = self.dal.get_for_user_for_update(address_id, user.id)
        if address is None:
            raise AddressNotFoundException()

        merged = self._merge_for_update(address, self.strip_client_identity_fields(data))
        prepared = self.prepare_update(user, merged)
        validated = self.validate(prepared, partial=True)
        fingerprint = self.compute_fingerprint(validated)
        if self.detect_duplicate(user.id, fingerprint, exclude_id=address.id):
            raise DuplicateAddressException()

        validated = self._maybe_geocode(validated)
        validated["formatted_address"] = AddressFormatter.format_from_dict(validated)
        validated["fingerprint"] = fingerprint

        self.dal.lock_user_addresses(user.id)
        if validated.get("is_default"):
            self.dal.unset_default_addresses(user.id, exclude_id=address.id)

        changed = {k: validated[k] for k in self._updatable_fields() if k in validated and getattr(address, k, None) != validated[k]}
        if changed:
            self.dal.update_fields(address, **changed)
        self.audit.log(
            address_id=address.id,
            user_id=user.id,
            actor_id=getattr(actor, "id", user.id),
            action=AddressAuditService.ACTION_UPDATE,
            changed_fields=changed,
        )
        AddressEventBus.publish(AddressUpdated(address.id, user.id, changed))
        return address

    @transaction.atomic
    def delete(self, user, address_id: UUID, *, actor=None) -> None:
        address = self.dal.get_for_user_for_update(address_id, user.id)
        if address is None:
            raise AddressNotFoundException()
        was_default = address.is_default
        self.dal.soft_delete(address)
        self.audit.log(
            address_id=address.id,
            user_id=user.id,
            actor_id=getattr(actor, "id", user.id),
            action=AddressAuditService.ACTION_DELETE,
        )
        AddressEventBus.publish(AddressDeleted(address.id, user.id))
        if was_default:
            replacement = self.dal.get_next_default_candidate(user.id, address.id)
            if replacement:
                self.dal.lock_user_addresses(user.id)
                self.dal.unset_default_addresses(user.id)
                self.dal.update_fields(replacement, is_default=True)
                AddressEventBus.publish(
                    AddressDefaultChanged(replacement.id, user.id, {"promoted_after_delete": str(address.id)})
                )

    @transaction.atomic
    def restore(self, user, address_id: UUID, *, actor=None) -> Address:
        address = self.dal.get_deleted_for_user_for_update(address_id, user.id)
        if address is None:
            raise AddressNotFoundException()
        self.dal.restore(address)
        self.audit.log(
            address_id=address.id,
            user_id=user.id,
            actor_id=getattr(actor, "id", user.id),
            action=AddressAuditService.ACTION_RESTORE,
        )
        AddressEventBus.publish(AddressRestored(address.id, user.id))
        return address

    @transaction.atomic
    def set_default(self, user, address_id: UUID, *, actor=None) -> Address:
        address = self.dal.get_for_user_for_update(address_id, user.id)
        if address is None:
            raise AddressNotFoundException()
        self.dal.lock_user_addresses(user.id)
        self.dal.unset_default_addresses(user.id, exclude_id=address.id)
        self.dal.update_fields(address, is_default=True)
        self.audit.log(
            address_id=address.id,
            user_id=user.id,
            actor_id=getattr(actor, "id", user.id),
            action=AddressAuditService.ACTION_SET_DEFAULT,
        )
        AddressEventBus.publish(AddressDefaultChanged(address.id, user.id))
        return address

    @transaction.atomic
    def change_verification(
        self,
        *,
        address: Address,
        status: str,
        verified_by,
        verification_source: str,
        actor=None,
    ) -> Address:
        fields = {
            "verification_status": status,
            "is_verified": status == VerificationStatus.VERIFIED,
            "verified_at": timezone.now() if status == VerificationStatus.VERIFIED else None,
            "verified_by": verified_by if status == VerificationStatus.VERIFIED else None,
            "verification_source": verification_source,
        }
        self.dal.update_fields(address, **fields)
        self.audit.log(
            address_id=address.id,
            user_id=address.user_id,
            actor_id=getattr(actor, "id", None),
            action=AddressAuditService.ACTION_VERIFICATION_CHANGE,
            changed_fields=fields,
        )
        AddressEventBus.publish(
            AddressVerificationChanged(address.id, address.user_id, fields)
        )
        return address

    # ------------------------------------------------------------------
    # Checkout / Snapshot
    # ------------------------------------------------------------------
    def resolve_checkout_snapshot(self, *, user, branch, delivery_data: dict[str, Any]) -> dict[str, Any]:
        """
        Build immutable order delivery snapshot with optional overrides.
        address_id wins; override fields: delivery_notes, building_number, unit, floor.
        """
        data = self._resolve_delivery_data(user, delivery_data)
        serviceability = self.evaluate_serviceability(user=user, branch=branch, delivery_data=delivery_data)
        if not serviceability.serviceable and serviceability.reason:
            raise AddressNotServiceableException(serviceability.reason)

        snapshot = data
        snapshot.update({
            "branch_id": branch.id,
            "delivery_zone": serviceability.delivery_zone,
            "verification_status": snapshot.get("verification_status", VerificationStatus.PENDING),
            "distance_km": serviceability.distance,
            "delivery_fee": serviceability.delivery_fee,
            "estimated_delivery_time": serviceability.estimated_delivery_time,
            "calculated_at": timezone.now(),
        })
        return snapshot

    def _snapshot_from_address(self, address: Address) -> dict[str, Any]:
        # OrderDeliveryAddress has no custom_label; fold display into title only.
        return {
            "source_address_id": address.id,
            "title": address.title or display_label(address.address_type, address.custom_label),
            "label": address.address_type,
            "address_type": address.address_type,
            "first_name": address.first_name,
            "last_name": address.last_name,
            "company": address.company,
            "phone": address.phone,
            "country_code": address.country_code,
            "country": address.country,
            "province": address.province,
            "city": address.city,
            "district": address.district,
            "street": address.street,
            "building_number": address.building_number,
            "unit": address.unit,
            "floor": address.floor,
            "postal_code": address.postal_code,
            "latitude": address.latitude,
            "longitude": address.longitude,
            "delivery_notes": address.delivery_notes,
            "formatted_address": address.formatted_address,
            "verification_status": address.verification_status,
        }

    def _snapshot_from_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        address_type = data.get("address_type", data.get("label", "other"))
        custom_label = data.get("custom_label", "")
        return {
            "source_address_id": data.get("address_id"),
            "title": display_label(address_type, custom_label) or "Delivery",
            "label": address_type,
            "address_type": address_type,
            "company": data.get("company", ""),
            "country": data.get("country", ""),
            "province": data.get("province", data.get("state", "")),
            "city": data["city"],
            "district": data.get("district", ""),
            "street": data["street"],
            "building_number": data.get("building_number", ""),
            "unit": data.get("unit", ""),
            "floor": data.get("floor", ""),
            "postal_code": data.get("postal_code", data.get("zip", "")),
            "latitude": data.get("latitude") if data.get("latitude") is not None else data.get("lat"),
            "longitude": data.get("longitude") if data.get("longitude") is not None else data.get("lng"),
            "delivery_notes": data.get("delivery_notes", ""),
            "verification_status": VerificationStatus.PENDING,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _maybe_geocode(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("latitude") is not None and data.get("longitude") is not None:
            return data
        result = self.geocoder.geocode_address(data)
        if result:
            data["latitude"] = result.point.latitude
            data["longitude"] = result.point.longitude
            if result.formatted_address:
                data["formatted_address"] = result.formatted_address
        return data

    @staticmethod
    def _merge_for_update(address: Address, data: dict[str, Any]) -> dict[str, Any]:
        base = {
            "title": address.title,
            "address_type": address.address_type,
            "custom_label": address.custom_label,
            "first_name": address.first_name,
            "last_name": address.last_name,
            "company": address.company,
            "phone": address.phone,
            "country_code": address.country_code,
            "country": address.country,
            "province": address.province,
            "city": address.city,
            "district": address.district,
            "street": address.street,
            "building_number": address.building_number,
            "unit": address.unit,
            "floor": address.floor,
            "postal_code": address.postal_code,
            "latitude": address.latitude,
            "longitude": address.longitude,
            "delivery_notes": address.delivery_notes,
            "is_default": address.is_default,
        }
        base.update(data)
        return base

    @staticmethod
    def _updatable_fields() -> tuple[str, ...]:
        return (
            "title", "address_type", "custom_label", "label", "first_name", "last_name",
            "company", "phone", "country_code", "country", "province", "city", "district",
            "street", "building_number", "unit", "floor", "postal_code", "latitude",
            "longitude", "delivery_notes", "is_default", "formatted_address", "fingerprint",
        )

    @staticmethod
    def _model_fields(data: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title", "address_type", "custom_label", "label", "first_name", "last_name",
            "company", "phone", "country_code", "country", "province", "city", "district",
            "street", "building_number", "unit", "floor", "postal_code", "latitude",
            "longitude", "delivery_notes", "is_default", "is_verified", "verification_status",
            "verified_at", "verification_method", "verification_source", "formatted_address", "fingerprint",
        }
        return {k: v for k, v in data.items() if k in allowed}
