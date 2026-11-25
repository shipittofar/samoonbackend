from typing import Optional
from uuid import UUID

from reservations.constants import PENDING_RESERVATION_STATUSES
from reservations.models import Reservation
from tenants.models import Branch
from tenants.selectors.tenant_availability import OPERATIONAL_TENANT_LOOKUP


class ReservationsDataAccessLayer:
    @staticmethod
    def create_reservation(**fields) -> Reservation:
        return Reservation.objects.create(**fields)

    @staticmethod
    def update_reservation_fields(reservation: Reservation, **fields) -> Reservation:
        for field_name, value in fields.items():
            setattr(reservation, field_name, value)
        reservation.save(update_fields=list(fields.keys()))
        return reservation

    @staticmethod
    def get_by_id(reservation_id: UUID) -> Optional[Reservation]:
        return (
            Reservation.objects.select_related(
                "branch",
                "branch__tenant",
                "branch__tenant__owner",
                "customer",
            )
            .filter(pk=reservation_id)
            .first()
        )

    @staticmethod
    def list_for_customer(customer):
        return (
            Reservation.objects.filter(customer=customer)
            .select_related("branch", "branch__tenant")
            .order_by("-reserved_at", "-created_at")
        )

    @staticmethod
    def get_for_update(reservation_id: UUID) -> Optional[Reservation]:
        return (
            Reservation.objects.select_related(
                "branch",
                "branch__tenant",
                "branch__tenant__owner",
                "branch__tenant__owner__user",
                "customer",
            )
            .select_for_update(of=("self",))
            .filter(pk=reservation_id)
            .first()
        )

    @staticmethod
    def get_active_branch(branch_id: UUID) -> Optional[Branch]:
        return (
            Branch.objects.select_related("tenant")
            .filter(pk=branch_id, is_active=True, **OPERATIONAL_TENANT_LOOKUP)
            .first()
        )

    @staticmethod
    def lock_branch(branch_id: UUID) -> None:
        """Serialize bookings of one branch, so two can't take the last seats."""
        Branch.objects.select_for_update().filter(pk=branch_id).values_list("pk").first()

    @staticmethod
    def branches_of_tenant(tenant_id: UUID):
        return list(Branch.objects.filter(tenant_id=tenant_id).select_related("tenant"))

    @staticmethod
    def list_for_branches(branch_ids):
        return (
            Reservation.objects.filter(branch_id__in=branch_ids)
            .select_related("branch", "branch__tenant", "customer")
            .order_by("reserved_at", "created_at")
        )

    @staticmethod
    def count_pending_for_branch(*, tenant_id: UUID, branch_id: UUID) -> int:
        return Reservation.objects.filter(
            branch_id=branch_id,
            branch__tenant_id=tenant_id,
            status__in=PENDING_RESERVATION_STATUSES,
        ).count()
