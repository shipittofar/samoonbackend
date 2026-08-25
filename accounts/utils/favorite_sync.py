import hashlib

from django.db.models import Count, Max
from django.utils import timezone

from accounts.models import Favorite


def compute_favorites_sync_state(*, user_id, branch_id=None) -> dict:
    """
    Deterministic sync token for a user's favorites collection.

    Changes whenever a favorite is added or removed, or when the set of
    non-deleted menu items in the collection changes.
    """
    queryset = Favorite.objects.filter(
        user_id=user_id,
        menu_item__deleted_at__isnull=True,
    )
    if branch_id is not None:
        queryset = queryset.filter(menu_item__branch_id=branch_id)

    stats = queryset.aggregate(
        total_count=Count("id"),
        latest_favorited_at=Max("created_at"),
    )
    total_count = stats["total_count"] or 0
    latest = stats["latest_favorited_at"]
    latest_iso = latest.isoformat() if latest else ""
    scope = branch_id or "all"
    version = hashlib.sha256(
        f"{user_id}:{scope}:{total_count}:{latest_iso}".encode()
    ).hexdigest()

    return {
        "version": version,
        "generated_at": timezone.now(),
        "total_count": total_count,
        "branch_id": str(branch_id) if branch_id is not None else None,
    }
