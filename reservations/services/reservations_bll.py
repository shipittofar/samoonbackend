from datetime import datetime, time, timedelta
from typing import Optional
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q

from access.authorization.console_workspace import (
    RESERVATIONS_CONSOLE_PERMISSIONS,
    authorize_console_branch,
    user_has_console_permissions,
)
from core.exceptions import (
    BranchNotFoundException,
    PermissionDeniedException,
    ReservationAlreadyBookedException,
    ReservationDurationUnavailableException,
    ReservationNotAdjustableException,
    ReservationTimeUnavailableException,
    InvalidReservationStatusTransitionException,
    PartySizeExceedsCapacityException,
    ReservationNotCancellableException,
    ReservationNotFoundException,
    ReservationsDisabledException,
)
from core.ws.publisher import RESERVATION_CHANGED, schedule_console_event_on_commit
from notifications import events as notification_events
from notifications.live import push_changes
from reservations.models import Reservation, ReservationStatus
from reservations.selectors import ReservationsDataAccessLayer
from reservations.services.rules import rules_for
from reservations.services.slots import ACTIVE_STATUSES, available_slots, branch_zone, longest_end


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

        zone = branch_zone(branch)
        reserved_at = validated_data.get("reserved_at") or datetime.combine(
            validated_data["date"], validated_data["time"], tzinfo=zone
        )

        with transaction.atomic():
            self.dal.lock_branch(branch.id)
            day = reserved_at.astimezone(zone).date()
            rules = rules_for(branch)
            if reserved_at not in available_slots(branch, day, party_size=party_size, rules=rules):
                raise ReservationTimeUnavailableException()
            if Reservation.objects.filter(
                customer=customer, branch=branch, status__in=ACTIVE_STATUSES,
                ends_at__gt=reserved_at,
                reserved_at__lt=reserved_at + timedelta(minutes=rules["duration_minutes"]),
            ).exists():
                raise ReservationAlreadyBookedException()
            reservation = self.dal.create_reservation(
                branch=branch,
                customer=customer,
                guest_name=validated_data["guest_name"],
                guest_phone=validated_data["guest_phone"],
                party_size=party_size,
                reserved_at=reserved_at,
                duration_minutes=rules["duration_minutes"],
                notes=validated_data.get("notes", ""),
                status=ReservationStatus.PENDING,
            )
            self._schedule_changed(reservation)
            notification_events.reservation_created(reservation)

        return self.dal.get_by_id(reservation.id)

    def get_available_slots(self, *, branch_id: UUID, day, party_size: int = 1) -> list[str]:
        """Bookable local times ("19:30") of one day. Public."""
        branch = self.dal.get_active_branch(branch_id)
        if branch is None:
            raise BranchNotFoundException()
        if not branch.reservations_enabled:
            raise ReservationsDisabledException()
        return [at.strftime("%H:%M") for at in available_slots(branch, day, party_size=party_size)]

    # ── Console ──────────────────────────────────────────────────────────────

    def _viewable_branches(self, *, user, tenant_id: UUID, branch_id: UUID | None = None) -> list:
        if branch_id is not None:
            return [
                authorize_console_branch(
                    user=user, tenant_id=tenant_id, branch_id=branch_id,
                    permission_slugs=RESERVATIONS_CONSOLE_PERMISSIONS,
                )
            ]
        branches = [
            b for b in self.dal.branches_of_tenant(tenant_id)
            if user_has_console_permissions(
                user=user, tenant_id=tenant_id, branch_id=b.id, permission_slugs=RESERVATIONS_CONSOLE_PERMISSIONS
            )
        ]
        if not branches:
            raise PermissionDeniedException()
        return branches

    def list_console_reservations(
        self, *, user, tenant_id: UUID, branch_id=None, day=None, status: str = "", search: str = ""
    ):
        """(queryset, {status: count}) for the branches ``user`` may view.
        ``day`` is each branch's local day; counts ignore the status filter."""
        branches = self._viewable_branches(user=user, tenant_id=tenant_id, branch_id=branch_id)
        qs = self.dal.list_for_branches([b.id for b in branches])
        if day is not None:
            on_day = Q()
            for branch in branches:
                zone = branch_zone(branch)
                start = datetime.combine(day, time.min, tzinfo=zone)
                end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
                on_day |= Q(branch_id=branch.id, reserved_at__gte=start, reserved_at__lt=end)
            qs = qs.filter(on_day)
        if search:
            qs = qs.filter(
                Q(guest_name__icontains=search) | Q(guest_phone__icontains=search) | Q(notes__icontains=search)
            )
        counts = dict(qs.order_by().values_list("status").annotate(n=Count("id")))
        if status:
            qs = qs.filter(status=status)
        return qs, counts

    def get_console_reservation(self, *, user, tenant_id: UUID, reservation_id: UUID) -> Reservation:
        reservation = self.dal.get_by_id(reservation_id)
        if reservation is None or reservation.branch.tenant_id != tenant_id:
            raise ReservationNotFoundException()
        authorize_console_branch(
            user=user, tenant_id=tenant_id, branch_id=reservation.branch_id,
            permission_slugs=RESERVATIONS_CONSOLE_PERMISSIONS,
        )
        return reservation

    def list_customer_reservations(self, *, customer):
        """The customer's own reservations at every business, latest first."""
        return self.dal.list_for_customer(customer)

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

    def update_reservation_duration(self, *, user, reservation_id: UUID, minutes: int) -> Reservation:
        """Make one reservation shorter, or longer when the time after it is free."""
        with transaction.atomic():
            reservation = self.dal.get_for_update(reservation_id)
            if reservation is None:
                raise ReservationNotFoundException()
            authorize_console_branch(
                user=user, tenant_id=reservation.branch.tenant_id, branch_id=reservation.branch_id,
                permission_slugs=("reservations.manage",),
            )
            if reservation.status not in ACTIVE_STATUSES:
                raise ReservationNotAdjustableException()
            if minutes == reservation.duration_minutes:
                return reservation
            # The same lock bookings take, so the free time cannot be taken meanwhile.
            self.dal.lock_branch(reservation.branch_id)
            if minutes > reservation.duration_minutes and (
                reservation.reserved_at + timedelta(minutes=minutes) > longest_end(reservation)
            ):
                raise ReservationDurationUnavailableException()
            self.dal.update_reservation_fields(reservation, duration_minutes=minutes)
            self._schedule_changed(reservation)
            notification_events.reservation_duration_changed(reservation, actor=user)

        return self.dal.get_by_id(reservation.id)

    def authorize_rules(self, *, user, tenant_id: UUID, branch_id: UUID, edit: bool):
        """The branch, when ``user`` may see (or change) its reservation rules."""
        return authorize_console_branch(
            user=user, tenant_id=tenant_id, branch_id=branch_id,
            permission_slugs=("settings.manage", "branches.manage") if edit else RESERVATIONS_CONSOLE_PERMISSIONS,
        )

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
        # The customer's open pages (seated / completed send no notification).
        push_changes([reservation.customer_id], ["reservations"])
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
