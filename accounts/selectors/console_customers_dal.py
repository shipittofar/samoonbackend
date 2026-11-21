from __future__ import annotations

from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, Concat, Greatest
from django.db.models.query import QuerySet

from accounts.models import User
from orders.models import Order
from reservations.models import Reservation


class ConsoleCustomersDataAccessLayer:
    """Read-only customer listing derived from Order and Reservation activity."""

    @staticmethod
    def list_customers_for_console_tenant(
        *,
        tenant_id,
        branch_id=None,
        search: str | None = None,
    ) -> QuerySet[User]:
        order_scope = ConsoleCustomersDataAccessLayer._scoped_orders(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )
        reservation_scope = ConsoleCustomersDataAccessLayer._scoped_reservations(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

        has_order = Exists(
            order_scope.filter(customer_id=OuterRef("pk"))
        )
        has_reservation = Exists(
            reservation_scope.filter(customer_id=OuterRef("pk"))
        )

        orders_count = Subquery(
            order_scope.filter(customer_id=OuterRef("pk"))
            .order_by()
            .values("customer_id")
            .annotate(c=Count("id"))
            .values("c")[:1],
            output_field=IntegerField(),
        )
        reservations_count = Subquery(
            reservation_scope.filter(customer_id=OuterRef("pk"))
            .order_by()
            .values("customer_id")
            .annotate(c=Count("id"))
            .values("c")[:1],
            output_field=IntegerField(),
        )
        last_order_at = Subquery(
            order_scope.filter(customer_id=OuterRef("pk"))
            .order_by("-created_at")
            .values("created_at")[:1],
            output_field=DateTimeField(),
        )
        last_reservation_at = Subquery(
            reservation_scope.filter(customer_id=OuterRef("pk"))
            .order_by("-created_at")
            .values("created_at")[:1],
            output_field=DateTimeField(),
        )

        queryset = (
            User.objects.filter(is_superuser=False)  # platform superusers are not customers
            .filter(Q(has_order) | Q(has_reservation))
            .annotate(
                orders_count=Coalesce(orders_count, Value(0)),
                reservations_count=Coalesce(reservations_count, Value(0)),
                last_order_at=last_order_at,
                last_reservation_at=last_reservation_at,
            )
            .annotate(
                last_activity_at=Greatest(
                    Coalesce("last_order_at", "last_reservation_at"),
                    Coalesce("last_reservation_at", "last_order_at"),
                ),
            )
        )

        if search:
            term = search.strip()
            if term:
                full_name = Concat(
                    Coalesce("first_name", Value("")),
                    Value(" "),
                    Coalesce("last_name", Value("")),
                    output_field=CharField(),
                )
                queryset = queryset.annotate(_search_full_name=full_name).filter(
                    Q(email__icontains=term)
                    | Q(phone_number__icontains=term)
                    | Q(first_name__icontains=term)
                    | Q(last_name__icontains=term)
                    | Q(_search_full_name__icontains=term)
                )

        return queryset.order_by("-last_activity_at", "id")

    @staticmethod
    def _scoped_orders(*, tenant_id, branch_id=None):
        queryset = Order.objects.filter(branch__tenant_id=tenant_id)
        if branch_id is not None:
            queryset = queryset.filter(branch_id=branch_id)
        return queryset

    @staticmethod
    def _scoped_reservations(*, tenant_id, branch_id=None):
        queryset = Reservation.objects.filter(branch__tenant_id=tenant_id)
        if branch_id is not None:
            queryset = queryset.filter(branch_id=branch_id)
        return queryset
