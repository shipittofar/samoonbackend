from orders.models import OrderStatus

# Console pending-order badge: only the initial `pending` status.
# OrderStatus.CONFIRMED is stored as "accepted" and is not pending.
PENDING_ORDER_STATUSES = frozenset({OrderStatus.PENDING})
