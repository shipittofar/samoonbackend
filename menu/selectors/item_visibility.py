"""
Single source of truth for menu-item visibility on public vs console reads.

``is_active`` controls publishing/visibility on public browse endpoints.
``available`` is a separate ordering flag and must never affect visibility.
"""

from menu.models import MenuItem


def active_items_only(items) -> list[MenuItem]:
    """Keep only items that are active for customer-facing responses."""
    return [item for item in items if item.is_active]


def queryset_public_active_items(branch_id):
    """Return a queryset of published items for a branch (visibility gate)."""
    return MenuItem.objects.filter(branch_id=branch_id, is_active=True)
