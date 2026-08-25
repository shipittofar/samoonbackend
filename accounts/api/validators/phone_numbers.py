import re
from rest_framework import serializers

COUNTRY_CODE_REGEX = re.compile(r"^\+[1-9]\d{0,3}$")
PHONE_NUMBER_REGEX = re.compile(r"^\d{6,14}$")


def validate_country_code(value: str) -> str:
    if not COUNTRY_CODE_REGEX.match(value):
        raise serializers.ValidationError(
            "country_code must start with '+' and contain digits only. Example: +98"
        )
    return value


def validate_phone_number(value: str) -> str:
    if not PHONE_NUMBER_REGEX.match(value):
        raise serializers.ValidationError(
            "phone_number must contain digits only (no spaces, '+' or '-'). Example: 9123456789"
        )
    return value


def build_full_phone(country_code: str, phone_number: str) -> str:
    return f"{country_code}{phone_number}"