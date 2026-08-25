from django.db import models


class AddressType(models.TextChoices):
    HOME = "home", "Home"
    WORK = "work", "Work"
    OFFICE = "office", "Office"
    WAREHOUSE = "warehouse", "Warehouse"
    OTHER = "other", "Other"


LEGACY_LABEL_MAP = {
    "home": AddressType.HOME,
    "work": AddressType.WORK,
    "office": AddressType.OFFICE,
    "parents": AddressType.OTHER,
    "custom": AddressType.OTHER,
    "warehouse": AddressType.WAREHOUSE,
}


def resolve_address_type(value: str | None, *, custom_label: str = "") -> str:
    if not value:
        return AddressType.HOME
    normalized = str(value).strip().lower()
    if normalized in AddressType.values:
        return normalized
    return LEGACY_LABEL_MAP.get(normalized, AddressType.OTHER)


def display_label(address_type: str, custom_label: str = "") -> str:
    if address_type == AddressType.OTHER and custom_label:
        return custom_label
    try:
        return AddressType(address_type).label
    except ValueError:
        return custom_label or "Other"
