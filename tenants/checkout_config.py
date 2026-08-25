"""Checkout configuration constants and helpers for Branch operational fields."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Legacy JSON keys removed from Branch.settings — never read after migration.
OPERATIONAL_SETTINGS_JSON_KEYS = frozenset({
    "deliveryEnabled",
    "pickupEnabled",
    "tableOrderingEnabled",
    "orderingEnabled",
    "deliveryRadius",
    "minimumOrder",
    "cashOnDeliveryEnabled",
    "sameDayDeliveryEnabled",
    "scheduledDeliveryEnabled",
    "contactlessDeliveryEnabled",
    "marketplaceVisible",
    "reservationsEnabled",
    "maxCapacity",
})

# camelCase API field → snake_case model field
CHECKOUT_CAMEL_TO_SNAKE = {
    "deliveryEnabled": "delivery_enabled",
    "pickupEnabled": "pickup_enabled",
    "tableOrderingEnabled": "table_ordering_enabled",
    "orderingEnabled": "ordering_enabled",
    "deliveryRadius": "delivery_radius_km",
    "minimumOrder": "minimum_order_amount",
    "defaultOrderType": "default_order_type",
    "cashPaymentEnabled": "cash_payment_enabled",
    "cardPaymentEnabled": "card_payment_enabled",
    "onlinePaymentEnabled": "online_payment_enabled",
    "walletPaymentEnabled": "wallet_payment_enabled",
    "cashOnDeliveryEnabled": "cash_on_delivery_enabled",
    "defaultPaymentMethod": "default_payment_method",
    "sameDayDeliveryEnabled": "same_day_delivery_enabled",
    "scheduledDeliveryEnabled": "scheduled_delivery_enabled",
    "contactlessDeliveryEnabled": "contactless_delivery_enabled",
    "marketplaceVisible": "marketplace_visible",
    "reservationsEnabled": "reservations_enabled",
    "maxCapacity": "max_capacity",
}

BRANCH_CHECKOUT_MODEL_FIELDS = tuple(CHECKOUT_CAMEL_TO_SNAKE.values())

# JSON key → model field (for data migration backfill)
JSON_KEY_TO_MODEL_FIELD = {
    "deliveryEnabled": "delivery_enabled",
    "pickupEnabled": "pickup_enabled",
    "tableOrderingEnabled": "table_ordering_enabled",
    "orderingEnabled": "ordering_enabled",
    "deliveryRadius": "delivery_radius_km",
    "minimumOrder": "minimum_order_amount",
    "cashOnDeliveryEnabled": "cash_on_delivery_enabled",
    "sameDayDeliveryEnabled": "same_day_delivery_enabled",
    "scheduledDeliveryEnabled": "scheduled_delivery_enabled",
    "contactlessDeliveryEnabled": "contactless_delivery_enabled",
    "marketplaceVisible": "marketplace_visible",
    "reservationsEnabled": "reservations_enabled",
    "maxCapacity": "max_capacity",
}


def default_branch_settings() -> dict:
    """Extension-only JSON defaults for Branch.settings."""
    return {}


def strip_operational_settings_keys(settings: dict | None) -> dict:
    """Return settings dict with operational checkout keys removed."""
    if not settings:
        return {}
    return {k: v for k, v in settings.items() if k not in OPERATIONAL_SETTINGS_JSON_KEYS}


def map_checkout_camel_to_snake(data: dict[str, Any]) -> dict[str, Any]:
    """Move top-level camelCase checkout fields into snake_case keys."""
    result = dict(data)
    for camel, snake in CHECKOUT_CAMEL_TO_SNAKE.items():
        if camel in result:
            result[snake] = result.pop(camel)
    return result


_ORDER_TYPE_ALIASES = {
    "dineIn": "dine_in",
    "dine_in": "dine_in",
    "delivery": "delivery",
    "pickup": "pickup",
}


def _normalize_order_type(value: Any) -> Any:
    if isinstance(value, str):
        return _ORDER_TYPE_ALIASES.get(value, value)
    return value


def flatten_nested_checkout(checkout: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested frontend ``checkout`` object into top-level camelCase keys."""
    flat: dict[str, Any] = {}

    if "orderingEnabled" in checkout:
        flat["orderingEnabled"] = checkout["orderingEnabled"]

    order_types = checkout.get("orderTypes") or {}
    if "delivery" in order_types:
        flat["deliveryEnabled"] = order_types["delivery"]
    if "pickup" in order_types:
        flat["pickupEnabled"] = order_types["pickup"]
    if "dineIn" in order_types:
        flat["tableOrderingEnabled"] = order_types["dineIn"]
    if "default" in order_types:
        flat["defaultOrderType"] = _normalize_order_type(order_types["default"])

    payments = checkout.get("payments") or {}
    payment_map = {
        "cash": "cashPaymentEnabled",
        "cashOnDelivery": "cashOnDeliveryEnabled",
        "card": "cardPaymentEnabled",
        "online": "onlinePaymentEnabled",
        "wallet": "walletPaymentEnabled",
    }
    for src, dest in payment_map.items():
        if src in payments:
            flat[dest] = payments[src]
    if "default" in payments:
        flat["defaultPaymentMethod"] = payments["default"]

    delivery = checkout.get("delivery") or {}
    if "radius" in delivery:
        flat["deliveryRadius"] = delivery["radius"]
    if "minimumOrder" in delivery:
        flat["minimumOrder"] = delivery["minimumOrder"]
    if "sameDay" in delivery:
        flat["sameDayDeliveryEnabled"] = delivery["sameDay"]
    if "scheduled" in delivery:
        flat["scheduledDeliveryEnabled"] = delivery["scheduled"]
    if "contactless" in delivery:
        flat["contactlessDeliveryEnabled"] = delivery["contactless"]

    for camel in CHECKOUT_CAMEL_TO_SNAKE:
        if camel in checkout:
            flat[camel] = checkout[camel]

    return flat


def extract_checkout_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Pop checkout model fields from a flat data dict."""
    extracted = {}
    for field in BRANCH_CHECKOUT_MODEL_FIELDS:
        if field in data:
            extracted[field] = data.pop(field)
    return extracted


def coerce_backfill_value(json_key: str, value: Any) -> Any:
    if value is None:
        return None
    if json_key == "minimumOrder":
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if json_key in ("deliveryRadius", "maxCapacity"):
        return int(value)
    if json_key in OPERATIONAL_SETTINGS_JSON_KEYS:
        return bool(value)
    return value
