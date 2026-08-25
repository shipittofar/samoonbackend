from __future__ import annotations

from typing import Any

from addresses.domain.address_type import display_label


class AddressFormatter:
    """Build canonical formatted_address strings for API responses."""

    @staticmethod
    def format_from_dict(data: dict[str, Any]) -> str:
        parts: list[str] = []
        street_line = " ".join(
            p for p in (
                data.get("street", ""),
                data.get("building_number", ""),
                data.get("unit", ""),
                f"Floor {data['floor']}" if data.get("floor") else "",
            ) if p
        ).strip()
        if street_line:
            parts.append(street_line)
        locality = ", ".join(
            p for p in (
                data.get("district", ""),
                data.get("city", ""),
                data.get("province", ""),
                data.get("postal_code", ""),
                data.get("country", ""),
            ) if p
        )
        if locality:
            parts.append(locality)
        return ", ".join(parts)

    @classmethod
    def format_address(cls, address) -> str:
        return cls.format_from_dict({
            "street": address.street,
            "building_number": address.building_number,
            "unit": address.unit,
            "floor": getattr(address, "floor", ""),
            "district": address.district,
            "city": address.city,
            "province": address.province,
            "postal_code": address.postal_code,
            "country": address.country,
        })

    @staticmethod
    def format_title(address) -> str:
        return display_label(
            getattr(address, "address_type", None) or getattr(address, "label", "other"),
            getattr(address, "custom_label", ""),
        ) or getattr(address, "title", "Address")
