import uuid

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
            models.Index(fields=["customer"]),
        ]

    def __str__(self):
        return f"Reservation {self.id} - {self.branch_id} ({self.status})"
