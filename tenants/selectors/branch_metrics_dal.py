from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from access.models import StaffAssignment, StaffMembershipStatus
from access.services.assignment_scope import (
    assignment_covers_branch_q,
    filter_assignments_tenant_wide,
)
from orders.models import Order, OrderStatus, PaymentStatus
from tenants.models import Branch


class BranchMetricsDataAccessLayer:
    """ORM access for branch-level aggregate metrics."""

    @staticmethod
    def get_branch_for_metrics(*, branch_id: UUID) -> Branch | None:
        return (
            Branch.objects.select_related("tenant")
            .filter(id=branch_id)
            .first()
        )

    @classmethod
    def compute_order_metrics(
        cls,
        *,
        branch_id: UUID,
        period_start: datetime | None,
    ) -> dict[str, Any]:
        base_qs = Order.objects.filter(branch_id=branch_id)
        if period_start is not None:
            base_qs = base_qs.filter(created_at__gte=period_start)

        revenue_qs = base_qs.exclude(status=OrderStatus.CANCELLED).exclude(
            payment_status__in=[PaymentStatus.REFUNDED, PaymentStatus.FAILED]
        )

        detail_stats = base_qs.aggregate(
            cancelled_orders=Count("id", filter=Q(status=OrderStatus.CANCELLED)),
            refunded_orders=Count(
                "id", filter=Q(payment_status=PaymentStatus.REFUNDED)
            ),
            failed_payments=Count(
                "id", filter=Q(payment_status=PaymentStatus.FAILED)
            ),
            pending_orders=Count("id", filter=Q(status=OrderStatus.PENDING)),
            completed_orders=Count(
                "id",
                filter=Q(
                    status__in=[OrderStatus.COMPLETED, OrderStatus.SERVED]
                ),
            ),
            guest_orders=Count("id", filter=Q(customer_id__isnull=True)),
            paid_orders=Count("id", filter=Q(payment_status=PaymentStatus.PAID)),
        )

        revenue_stats = revenue_qs.aggregate(
            total_orders=Count("id"),
            total_revenue=Coalesce(Sum("total"), Decimal("0")),
            total_customers=Count(
                "customer_id",
                distinct=True,
                filter=Q(customer_id__isnull=False),
            ),
        )

        total_orders = revenue_stats["total_orders"] or 0
        total_revenue = revenue_stats["total_revenue"] or Decimal("0")
        total_customers = revenue_stats["total_customers"] or 0

        if total_orders > 0:
            average_order_value = (total_revenue / total_orders).quantize(
                Decimal("0.01")
            )
        else:
            average_order_value = Decimal("0")

        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_customers": total_customers,
            "average_order_value": average_order_value,
            **detail_stats,
        }

    @staticmethod
    def compute_staff_metrics(*, branch_id: UUID, tenant_id: UUID) -> dict[str, int]:
        scoped_assignments = StaffAssignment.objects.filter(
            membership__tenant_id=tenant_id,
        ).filter(assignment_covers_branch_q(branch_id=branch_id))

        stats = scoped_assignments.aggregate(
            active=Count(
                "membership__user_id",
                distinct=True,
                filter=Q(
                    membership__status=StaffMembershipStatus.ACTIVE,
                    membership__user__is_deleted=False,
                ),
            ),
            inactive=Count(
                "membership__user_id",
                distinct=True,
                filter=Q(
                    membership__status__in=[
                        StaffMembershipStatus.SUSPENDED,
                        StaffMembershipStatus.REMOVED,
                    ],
                    membership__user__is_deleted=False,
                ),
            ),
        )

        tenant_wide_assignments = (
            filter_assignments_tenant_wide(
                StaffAssignment.objects.filter(membership__tenant_id=tenant_id)
            )
            .filter(
                membership__status=StaffMembershipStatus.ACTIVE,
                membership__user__is_deleted=False,
            )
            .values("membership__user_id")
            .distinct()
            .count()
        )

        return {
            "active": stats["active"] or 0,
            "inactive": stats["inactive"] or 0,
            "tenant_wide_assignments": tenant_wide_assignments,
        }
