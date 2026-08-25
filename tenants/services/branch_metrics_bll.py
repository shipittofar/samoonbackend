from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone as django_timezone

from core.exceptions import BranchNotFoundException
from tenants.selectors.branch_metrics_dal import BranchMetricsDataAccessLayer

VALID_PERIODS = frozenset({"day", "week", "month", "all"})
DEFAULT_PERIOD = "month"


class BranchMetricsBusinessLogicLayer:
    def __init__(self, dal: BranchMetricsDataAccessLayer | None = None):
        self.dal = dal or BranchMetricsDataAccessLayer()

    def get_branch_metrics(
        self,
        *,
        branch_id: UUID,
        period: str | None = None,
    ) -> dict[str, Any]:
        resolved_period = self._resolve_period(period)

        branch = self.dal.get_branch_for_metrics(branch_id=branch_id)
        if branch is None:
            raise BranchNotFoundException()

        period_start = self._period_start(branch.time_zone or "UTC", resolved_period)

        order_metrics = self.dal.compute_order_metrics(
            branch_id=branch_id,
            period_start=period_start,
        )
        staff_metrics = self.dal.compute_staff_metrics(
            branch_id=branch_id,
            tenant_id=branch.tenant_id,
        )

        return {
            "branch_id": branch.id,
            "total_orders": order_metrics["total_orders"],
            "total_revenue": order_metrics["total_revenue"],
            "total_reservations": 0,
            "total_customers": order_metrics["total_customers"],
            "staff_count": staff_metrics["active"],
            "average_order_value": order_metrics["average_order_value"],
            "period": resolved_period,
            "details": {
                "cancelled_orders": order_metrics["cancelled_orders"],
                "refunded_orders": order_metrics["refunded_orders"],
                "failed_payments": order_metrics["failed_payments"],
                "pending_orders": order_metrics["pending_orders"],
                "completed_orders": order_metrics["completed_orders"],
                "guest_orders": order_metrics["guest_orders"],
                "paid_orders": order_metrics["paid_orders"],
                "staff": {
                    "active": staff_metrics["active"],
                    "inactive": staff_metrics["inactive"],
                    "tenant_wide_assignments": staff_metrics["tenant_wide_assignments"],
                    "manager_included": False,
                },
                "reservation": {
                    "implemented": False,
                    "value": 0,
                },
                "calculation": {
                    "order_date_field": "created_at",
                    "period": resolved_period,
                },
            },
        }

    @staticmethod
    def _resolve_period(period: str | None) -> str:
        if period is None or period == "":
            return DEFAULT_PERIOD
        if period not in VALID_PERIODS:
            raise ValueError(
                f"Invalid period '{period}'. Must be one of: day, week, month, all."
            )
        return period

    @staticmethod
    def _period_start(time_zone: str, period: str) -> datetime | None:
        if period == "all":
            return None

        try:
            tz = ZoneInfo(time_zone)
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = django_timezone.now().astimezone(tz)

        if period == "day":
            start_local = now_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif period == "week":
            start_local = (now_local - timedelta(days=now_local.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif period == "month":
            start_local = now_local.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        else:
            return None

        return start_local.astimezone(dt_timezone.utc)
