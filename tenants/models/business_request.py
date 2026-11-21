"""Business registration requests.

Anyone signed in can ask to register a business with a short form. A
platform superuser approves or rejects it. Approval creates the owner
profile, the business and its first branch from the request, and the
console opens for the applicant, who then completes the details.
"""
import uuid

from django.conf import settings
from django.db import models

from tenants.constants.business_type import BusinessType


class BusinessRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class BusinessRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_requests"
    )
    status = models.CharField(
        max_length=16, choices=BusinessRequestStatus.choices,
        default=BusinessRequestStatus.PENDING, db_index=True,
    )

    # What the applicant filled in (a short version of the tenant wizard).
    name = models.CharField(max_length=255)
    business_type = models.CharField(max_length=30, choices=BusinessType.choices)
    description = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    address = models.TextField(blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    service_radius_km = models.PositiveIntegerField(null=True, blank=True)

    # Decision.
    rejection_reason = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="The business created on approval.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "business_requests"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="one_pending_business_request_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"
