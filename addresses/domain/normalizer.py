from __future__ import annotations

import re
import unicodedata
from typing import Any

from accounts.api.validators.phone_numbers import validate_phone_number
from addresses.domain.address_type import resolve_address_type
from addresses.validators import validate_iso_country, validate_postal_code

WHITESPACE_RE = re.compile(r"\s+")


class AddressNormalizer:
    """Normalize address fields before validation and persistence."""

    @classmethod
    def normalize_text(cls, value: str | None) -> str:
        if not value:
            return ""
        text = unicodedata.normalize("NFKC", str(value))
        return WHITESPACE_RE.sub(" ", text).strip()

    @classmethod
    def normalize_country(cls, value: str | None) -> str:
        return validate_iso_country(cls.normalize_text(value) or "US")

    @classmethod
    def normalize_phone(cls, value: str | None) -> str:
        digits = re.sub(r"\D", "", cls.normalize_text(value))
        return validate_phone_number(digits)

    @classmethod
    def normalize_postal_code(cls, value: str | None, *, country: str) -> str:
        cleaned = cls.normalize_text(value).upper()
        return validate_postal_code(cleaned or "00000", country=country)

    @classmethod
    def normalize_payload(cls, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        text_fields = (
            "title", "custom_label", "first_name", "last_name", "company",
            "province", "city", "district", "street", "building_number",
            "unit", "floor", "delivery_notes",
        )
        for field in text_fields:
            if field in normalized and normalized[field] is not None:
                normalized[field] = cls.normalize_text(normalized[field])

        if "country" in normalized:
            normalized["country"] = cls.normalize_country(normalized.get("country"))

        country = normalized.get("country", "US")
        if "postal_code" in normalized:
            normalized["postal_code"] = cls.normalize_postal_code(
                normalized.get("postal_code"), country=country
            )
        elif "zip" in normalized:
            normalized["postal_code"] = cls.normalize_postal_code(
                normalized.get("zip"), country=country
            )

        if "phone" in normalized and normalized["phone"]:
            normalized["phone"] = cls.normalize_phone(normalized["phone"])

        if "address_id" in data and data.get("address_id") not in (None, ""):
            normalized["address_id"] = data["address_id"]

        address_type = normalized.get("address_type") or normalized.get("label")
        custom_label = normalized.get("custom_label", "")
        normalized["address_type"] = resolve_address_type(address_type, custom_label=custom_label)
        if normalized["address_type"] == "other":
            normalized["custom_label"] = cls.normalize_text(custom_label)
        else:
            normalized["custom_label"] = ""

        # Legacy alias sync
        normalized["label"] = normalized["address_type"]

        return normalized
