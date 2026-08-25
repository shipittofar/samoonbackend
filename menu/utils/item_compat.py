"""Shared computed-field helpers for MenuItem frontend compatibility."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

IS_NEW_DAYS = 30


def compute_discounted_price(price, discount) -> Decimal | None:
    """Return price after percentage discount, or None when no discount applies."""
    if discount is None or discount <= 0:
        return None
    result = Decimal(price) * (1 - Decimal(discount) / Decimal(100))
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_is_new(created_at) -> bool:
    if created_at is None:
        return False
    return created_at >= timezone.now() - timedelta(days=IS_NEW_DAYS)


def compute_rating() -> Decimal:
    """Placeholder until per-item review aggregation exists."""
    return Decimal("0.00")


def compute_rating_count() -> int:
    """Placeholder until per-item review aggregation exists."""
    return 0


def build_nutritional_info(calories):
    if calories is None:
        return None
    return {
        "calories": calories,
        "protein": 0,
        "carbs": 0,
        "fat": 0,
    }


def serialize_materialized_extras(item) -> list[dict]:
    """Flatten MenuItemExtra links into the frontend Extra wire shape."""
    links = getattr(item, "_prefetched_objects_cache", {}).get("item_extras")
    if links is None:
        links = item.item_extras.select_related("extra").all()

    extras = []
    for link in links:
        extra = link.extra
        if not extra.available:
            continue
        payload = {
            "id": str(extra.id),
            "name": link.name,
            "price": link.price,
            "available": link.available,
            "branch_id": str(extra.branch_id),
        }
        if extra.group_id is not None:
            payload["group_id"] = str(extra.group_id)
        extras.append(payload)
    return extras
