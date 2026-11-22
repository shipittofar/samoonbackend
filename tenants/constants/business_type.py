from django.db import models


class BusinessType(models.TextChoices):
    RESTAURANT = "restaurant", "Restaurant"
    CAFE = "cafe", "Cafe"
    BAR = "bar", "Bar"
    FOOD_TRUCK = "food_truck", "Food Truck"
    FOOD_COURT = "food_court", "Food Court"
    MOBILE_CAFE = "mobile_cafe", "Mobile Cafe"
    GYM = "gym", "Gym"
    BEAUTY_SALON = "beauty_salon", "Beauty Salon"
    CLINIC = "clinic", "Clinic"


BUSINESS_TYPE_VALUES = frozenset(choice.value for choice in BusinessType)


def normalize_business_types(values: list[str] | None) -> list[str]:
    """Map legacy values and return a deduplicated list preserving order."""
    if not values:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value == "coffee":
            value = BusinessType.CAFE
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def validate_business_types(values: list[str] | None) -> list[str]:
    normalized = normalize_business_types(values)
    invalid = [value for value in normalized if value not in BUSINESS_TYPE_VALUES]
    if invalid:
        allowed = ", ".join(sorted(BUSINESS_TYPE_VALUES))
        raise ValueError(
            f"Invalid business type(s): {', '.join(invalid)}. "
            f"Allowed values are: {allowed}."
        )
    return normalized
