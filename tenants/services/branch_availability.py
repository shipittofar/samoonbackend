from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone as django_timezone


def _resolve_now(now: datetime | None) -> datetime:
    if now is not None:
        if django_timezone.is_naive(now):
            return django_timezone.make_aware(now, ZoneInfo("UTC"))
        return now
    return django_timezone.now()


def _branch_timezone(branch) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(branch, "time_zone", None) or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _iter_working_hours(branch):
    working_hours = getattr(branch, "working_hours", None)
    if working_hours is None:
        return []
    if isinstance(working_hours, list):
        return working_hours
    # ORM RelatedManager / Prefetch cache
    if (
        hasattr(working_hours, "_result_cache")
        and working_hours._result_cache is not None
    ):
        return working_hours._result_cache
    return list(working_hours.all())


def get_today_working_hour(
    branch,
    now: datetime | None = None,
):
    """Return today's working-hour row for the branch in its local timezone."""
    local_now = _resolve_now(now).astimezone(_branch_timezone(branch))
    weekday = local_now.weekday()

    for entry in _iter_working_hours(branch):
        if entry.day == weekday:
            return entry
    return None


def format_today_hours(
    branch,
    now: datetime | None = None,
) -> str | None:
    working_hour = get_today_working_hour(branch, now=now)
    if working_hour is None:
        return None
    if working_hour.is_closed:
        return "Closed today"
    if working_hour.open_time and working_hour.close_time:
        return (
            f"{working_hour.open_time:%H:%M}"
            f"-"
            f"{working_hour.close_time:%H:%M}"
        )
    return None


def is_branch_open(branch, now: datetime | None = None) -> bool:
    if not getattr(branch, "is_active", False) or getattr(branch, "status", None) != "active":
        return False

    working_hour = get_today_working_hour(branch, now=now)
    if working_hour is None or working_hour.is_closed:
        return False
    if not working_hour.open_time or not working_hour.close_time:
        return False

    local_now = _resolve_now(now).astimezone(_branch_timezone(branch))
    current_time = local_now.time()
    return working_hour.open_time <= current_time <= working_hour.close_time


def get_branch_availability(
    branch,
    now: datetime | None = None,
) -> dict[str, bool | str | None]:
    return {
        "openNow": is_branch_open(branch, now=now),
        "todayHours": format_today_hours(branch, now=now),
    }
