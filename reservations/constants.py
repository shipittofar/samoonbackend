from reservations.models import ReservationStatus

# Console pending-reservation badge: only the initial `pending` status.
PENDING_RESERVATION_STATUSES = frozenset({ReservationStatus.PENDING})
