import re

from django.conf import settings
from rest_framework import serializers

from accounts.api.validators.phone_numbers import (
    validate_country_code,
    validate_phone_number,
)

ISO_COUNTRY_CODE_REGEX = re.compile(r"^[A-Z]{2}$")
POSTAL_CODE_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s\-]{2,18}[A-Za-z0-9]$")


def validate_iso_country(value: str) -> str:
    value = value.strip().upper()
    if not ISO_COUNTRY_CODE_REGEX.match(value):
        raise serializers.ValidationError(
            "country must be a 2-letter ISO 3166-1 alpha-2 code (e.g. US, IR)."
        )
    return value


def validate_postal_code(value: str, *, country: str | None = None) -> str:
    value = value.strip()
    if not value:
        raise serializers.ValidationError("postal_code is required.")
    if country and country.upper() == "US" and not re.match(r"^\d{5}(-\d{4})?$", value):
        raise serializers.ValidationError(
            "US postal_code must be 12345 or 12345-6789."
        )
    if not POSTAL_CODE_REGEX.match(value):
        raise serializers.ValidationError("postal_code format is invalid.")
    return value


def validate_coordinates(latitude, longitude):
    if latitude is None and longitude is None:
        return
    if latitude is None or longitude is None:
        raise serializers.ValidationError(
            "Both latitude and longitude must be provided together."
        )
    if not (-90 <= latitude <= 90):
        raise serializers.ValidationError("latitude must be between -90 and 90.")
    if not (-180 <= longitude <= 180):
        raise serializers.ValidationError("longitude must be between -180 and 180.")


def get_max_user_addresses() -> int:
    return int(getattr(settings, "MAX_USER_ADDRESSES", 20))
