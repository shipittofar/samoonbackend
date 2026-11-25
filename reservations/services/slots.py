"""Which times a branch can be booked for, and how long a reservation can run.

Slots lie inside the branch's working hours, in the branch's own time zone;
their spacing, length and horizon come from reservations.services.rules. Two
limits apply to everything running at the same moment: the guests
(``branch.max_capacity``) and the number of reservations (``max_concurrent``).
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from reservations.models import Reservation, ReservationStatus
from reservations.services.rules import LIMITS, rules_for

# A branch that never filled in its working hours.
DEFAULT_OPEN, DEFAULT_CLOSE = time(12, 0), time(22, 0)
ACTIVE_STATUSES = (ReservationStatus.PENDING, ReservationStatus.CONFIRMED, ReservationStatus.SEATED)
LONGEST = timedelta(minutes=LIMITS["duration_minutes"][1])


def branch_zone(branch) -> ZoneInfo:
    """The branch's time zone. "UTC" is the untouched model default, not a
    place, so it means the platform's BUSINESS_TIME_ZONE."""
    name = (getattr(branch, "time_zone", "") or "").strip()
    if name and name != "UTC":
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError, OSError):
            pass
    return ZoneInfo(settings.BUSINESS_TIME_ZONE)


class Occupancy:
    """What is already booked at a branch between two moments."""

    def __init__(self, branch, start: datetime, end: datetime, rules: dict, *, exclude_id=None):
        self.max_guests = branch.max_capacity
        self.max_reservations = rules["max_concurrent"]
        self.rows: list[tuple[datetime, datetime, int]] = []
        if self.max_guests is None and self.max_reservations is None:
            return  # nothing to run out of
        qs = Reservation.objects.filter(
            branch=branch, status__in=ACTIVE_STATUSES, reserved_at__lt=end, ends_at__gt=start
        )
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        self.rows = list(qs.values_list("reserved_at", "ends_at", "party_size"))

    def _fits_at(self, moment: datetime, guests: int) -> bool:
        running = [size for start, end, size in self.rows if start <= moment < end]
        if self.max_guests is not None and sum(running) + guests > self.max_guests:
            return False
        return self.max_reservations is None or len(running) + 1 <= self.max_reservations

    def free_until(self, start: datetime, limit: datetime, guests: int) -> datetime:
        """The latest end (up to ``limit``) a reservation from ``start`` could
        have; ``start`` itself when there is no room at all."""
        # Occupancy only grows when another reservation begins.
        moments = sorted({start, *(s for s, _, _ in self.rows if start < s < limit)})
        for moment in moments:
            if not self._fits_at(moment, guests):
                return moment
        return limit

    def fits(self, start: datetime, end: datetime, guests: int) -> bool:
        return self.free_until(start, end, guests) >= end


def _opening(day: date_type, hours: dict, zone: ZoneInfo):
    """(opens, closes) of one day as aware datetimes, or None when closed."""
    if hours:
        row = hours.get(day.weekday())
        if row is None or row.is_closed or row.open_time is None or row.close_time is None:
            return None
        opens, closes = row.open_time, row.close_time
    else:
        opens, closes = DEFAULT_OPEN, DEFAULT_CLOSE
    start = datetime.combine(day, opens, tzinfo=zone)
    # Closing at or before opening means after midnight (18:00-02:00).
    end = datetime.combine(day + timedelta(days=1) if closes <= opens else day, closes, tzinfo=zone)
    return start, end


def available_slots(branch, day: date_type, *, party_size: int = 1, now=None, rules: dict | None = None) -> list[datetime]:
    """Bookable start times on the branch's local ``day``, earliest first."""
    now = now or timezone.now()
    rules = rules or rules_for(branch)
    zone = branch_zone(branch)
    if not 0 <= (day - now.astimezone(zone).date()).days <= rules["max_days_ahead"]:
        return []
    step = timedelta(minutes=rules["slot_minutes"])
    length = timedelta(minutes=rules["duration_minutes"])
    last = timedelta(minutes=rules["last_before_close_minutes"])
    lead = timedelta(minutes=rules["lead_minutes"])

    hours = {row.day: row for row in branch.working_hours.all()}
    day_start = datetime.combine(day, time.min, tzinfo=zone)
    busy = Occupancy(branch, day_start, day_start + timedelta(days=1) + length, rules)
    slots: set[datetime] = set()
    # Yesterday too: its opening hours may run past midnight into this day.
    for opening_day in (day - timedelta(days=1), day):
        window = _opening(opening_day, hours, zone)
        if window is None:
            continue
        at, end = window
        while at < end and at + last <= end:
            if at.date() == day and at >= now + lead and busy.fits(at, at + length, party_size):
                slots.add(at)
            at += step
    return sorted(slots)


def longest_end(reservation) -> datetime:
    """The latest moment this reservation could be extended to."""
    branch = reservation.branch
    limit = reservation.reserved_at + LONGEST
    busy = Occupancy(branch, reservation.reserved_at, limit, rules_for(branch), exclude_id=reservation.id)
    return busy.free_until(reservation.reserved_at, limit, reservation.party_size)
