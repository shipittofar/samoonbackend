from typing import Optional
from uuid import UUID

from django.db import transaction

from access.authorization.console_workspace import (
    RESERVATIONS_CONSOLE_PERMISSIONS,
    authorize_console_branch,
)
from core.exceptions import (
    BranchNotFoundException,
    InvalidReservationStatusTransitionException,
    PartySizeExceedsCapacityException,
    ReservationNotCancellableException,
    ReservationNotFoundException,
    ReservationsDisabledException,
)
from core.ws.publisher import RESERVATION_CHANGED, schedule_console_event_on_commit
from notifications import events as notification_events
from reservations.models import Reservation, ReservationStatus
from reservations.selectors import ReservationsDataAccessLayer


CANCELLABLE_STATUSES = {ReservationStatus.PENDING, ReservationStatus.CONFIRMED}

STATUS_TRANSITIONS = {
    ReservationStatus.PENDING: {
        ReservationStatus.CONFIRMED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.CONFIRMED: {
        ReservationStatus.SEATED,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    },
    ReservationStatus.SEATED: {
        ReservationStatus.COMPLETED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.COMPLETED: set(),
    ReservationStatus.CANCELLED: set(),
    ReservationStatus.NO_SHOW: set(),
}


class ReservationsBusinessLogicLayer:
    def __init__(self, dal: Optional[ReservationsDataAccessLayer] = None):
        self.dal = dal or ReservationsDataAccessLayer()

    def create_reservation(self, *, customer, validated_data: dict) -> Reservation:
        branch = self.dal.get_active_branch(validated_data["branch_id"])
        if branch is None:
            raise BranchNotFoundException()
        if not branch.reservations_enabled:
            raise ReservationsDisabledException()

        party_size = validated_data["party_size"]
        if branch.max_capacity is not None and party_size > branch.max_capacity:
            raise PartySizeExceedsCapacityException()

        with transaction.atomic():
            reservation = self.dal.create_reservation(
                branch=branch,
                customer=customer,
                guest_name=validated_data["guest_name"],
                guest_phone=validated_data["guest_phone"],
                party_size=party_size,
                reserved_at=validated_data["reserved_at"],
                notes=validated_data.get("notes", ""),
                status=ReservationStatus.PENDING,
            )
            self._schedule_changed(reservation)
            notification_events.reservation_created(reservation)

        return self.dal.get_by_id(reservation.id)

    def cancel_reservation(self, *, customer, reservation_id: UUID) -> Reservation:
        with transaction.atomic():
            reservation = self.dal.get_for_update(reservation_id)
            if reservation is None or reservation.customer_id != customer.id:
                raise ReservationNotFoundException()

            if reservation.status == ReservationStatus.CANCELLED:
                return reservation
            if reservation.status not in CANCELLABLE_STATUSES:
                raise ReservationNotCancellableException()

            self.dal.update_reservation_fields(
                reservation, status=ReservationStatus.CANCELLED
            )
            self._schedule_changed(reservation)
            notification_events.reservation_status_changed(reservation, actor=customer)

        return self.dal.get_by_id(reservation.id)

    def update_reservation_status(
        self, *, user, reservation_id: UUID, new_status: str
    ) -> Reservation:
        with transaction.atomic():
            reservation = self.dal.get_for_update(reservation_id)
            if reservation is None:
                raise ReservationNotFoundException()

            authorize_console_branch(
                user=user,
                tenant_id=reservation.branch.tenant_id,
                branch_id=reservation.branch_id,
                permission_slugs=("reservations.manage",),
            )

            allowed = STATUS_TRANSITIONS.get(reservation.status, set())
            if new_status not in allowed:
                raise InvalidReservationStatusTransitionException(
                    f"Cannot move reservation from '{reservation.status}' to '{new_status}'."
                )

            self.dal.update_reservation_fields(reservation, status=new_status)
            self._schedule_changed(reservation)
            notification_events.reservation_status_changed(reservation, actor=user)

        return self.dal.get_by_id(reservation.id)

    def get_pending_reservation_count(
        self,
        *,
        user,
        tenant_id: UUID,
        branch_id: UUID,
    ) -> int:
        authorize_console_branch(
            user=user,
            tenant_id=tenant_id,
            branch_id=branch_id,
            permission_slugs=RESERVATIONS_CONSOLE_PERMISSIONS,
        )
        return self.dal.count_pending_for_branch(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

    @staticmethod
    def _schedule_changed(reservation: Reservation) -> None:
        schedule_console_event_on_commit(
            tenant_id=reservation.branch.tenant_id,
            branch_id=reservation.branch_id,
            event_type=RESERVATION_CHANGED,
            data={
                "tenant_id": str(reservation.branch.tenant_id),
                "branch_id": str(reservation.branch_id),
                "reservation_id": str(reservation.id),
                "status": reservation.status,
            },
        )
