"""One way to turn a typed phone number into the stored form.

Stored form: ``country_code`` + national number without the trunk 0,
e.g. "+98" + "9121234567" -> "+989121234567". Sign-up, login, OTP, password
reset, phone verification and ``admin_add`` all go through here, so
"09121234567", "9121234567", "+98 912 123 4567" and Persian digits all
reach the same account.
"""
from __future__ import annotations

import re

COUNTRY_CODE_RE = re.compile(r"^\+[1-9]\d{0,3}$")
NATIONAL_RE = re.compile(r"^\d{6,14}$")

# Italy dials the leading 0 even in international form (+39 06…).
KEEPS_TRUNK_ZERO = frozenset({"+39"})

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = re.compile(r"[\s\-().‌‏‎]")


class InvalidPhoneNumber(ValueError):
    """The message is safe to show to the person who typed the number."""


def clean_country_code(raw: str | None) -> str:
    value = _SEPARATORS.sub("", (raw or "").translate(_DIGITS))
    if not COUNTRY_CODE_RE.match(value):
        raise InvalidPhoneNumber("country_code must look like +98.")
    return value


def normalize_national(country_code: str, raw: str | None) -> str:
    """The national part, digits only, without the trunk 0."""
    value = _SEPARATORS.sub("", (raw or "").translate(_DIGITS))
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        if not value.startswith(country_code):
            raise InvalidPhoneNumber(
                f"The number does not start with {country_code}; check the country code."
            )
        value = value[len(country_code):]
    if country_code not in KEEPS_TRUNK_ZERO:
        value = value.lstrip("0")
    if not NATIONAL_RE.match(value):
        raise InvalidPhoneNumber("That is not a valid phone number. Example: 9123456789")
    return value


def full_phone(country_code: str, raw: str | None) -> str:
    """Stored form of a number. Raises InvalidPhoneNumber."""
    code = clean_country_code(country_code)
    return f"{code}{normalize_national(code, raw)}"
