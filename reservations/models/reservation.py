import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models


class ReservationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    SEATED = "seated", "Seated"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No show"


class Reservation(models.Model):
    """Customer table reservation for a specific branch."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservations",
    )

    guest_name = models.CharField(max_length=255)
    guest_phone = models.CharField(max_length=32)
    party_size = models.PositiveIntegerField()
    reserved_at = models.DateTimeField()
    # Fixed when booked, so changing the branch's rules never moves it; staff
    # can change it for this one reservation.
    duration_minutes = models.PositiveIntegerField(default=120)
    # reserved_at + duration_minutes, kept by save() for overlap queries.
    ends_at = models.DateTimeField(editable=False)
    notes = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reservation"
        ordering = ["-reserved_at"]
        indexes = [
            models.Index(fields=["branch"]),
            models.Index(fields=["status"]),
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["reserved_at"]),
            models.Index(fields=["branch", "ends_at"], name="reservation_branch_ends_idx"),
            models.Index(fields=["customer"]),
        ]

    def save(self, *args, update_fields=None, **kwargs):
        self.ends_at = self.reserved_at + timedelta(minutes=self.duration_minutes)
        if update_fields is not None and {"reserved_at", "duration_minutes"} & set(update_fields):
            update_fields = {*update_fields, "ends_at"}
        super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return f"Reservation {self.id} - {self.branch_id} ({self.status})"


class BranchReservationRules(models.Model):
    """A branch's own reservation rules; empty = inherited (services/rules.py)."""

    branch = models.OneToOneField("tenants.Branch", on_delete=models.CASCADE, related_name="reservation_rules")
    slot_minutes = models.PositiveIntegerField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    last_before_close_minutes = models.PositiveIntegerField(null=True, blank=True)
    lead_minutes = models.PositiveIntegerField(null=True, blank=True)
    max_days_ahead = models.PositiveIntegerField(null=True, blank=True)
    max_concurrent = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "branch_reservation_rules"

    def __str__(self):
        return f"Reservation rules {self.branch_id}"
