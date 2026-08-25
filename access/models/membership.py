# access/models/membership.py
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class StaffMembershipStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    REMOVED = "removed", "Removed"


class AssignmentMode(models.TextChoices):
    READ = "read", "Read"
    MANAGE = "manage", "Manage"


class AssignmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    FUTURE = "future", "Future"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


class StaffMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="staff_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_memberships",
    )

    status = models.CharField(
        max_length=20,
        choices=StaffMembershipStatus.choices,
        default=StaffMembershipStatus.PENDING,
    )

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="staff_invitations_sent",
        null=True,
        blank=True,
    )
    joined_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant"], name="unique_user_tenant_membership"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.phone_number or self.user.email} | {self.tenant.name} ({self.status})"


class StaffAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    membership = models.ForeignKey(
        StaffMembership,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    role = models.ForeignKey(
        "access.Role",
        on_delete=models.PROTECT,
        related_name="staff_assignments",
    )
    all_locations = models.BooleanField(default=False)
    mode = models.CharField(
        max_length=10,
        choices=AssignmentMode.choices,
        default=AssignmentMode.MANAGE,
    )
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE,
    )
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="granted_staff_assignments",
        null=True,
        blank=True,
    )
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="revoked_staff_assignments",
        null=True,
        blank=True,
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "role"],
                condition=models.Q(
                    status__in=[
                        AssignmentStatus.ACTIVE,
                        AssignmentStatus.FUTURE,
                    ]
                ),
                name="unique_non_terminal_membership_role_grant",
            ),
        ]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["membership", "status"]),
        ]

    def clean(self):
        if self.role_id and getattr(self.role, "slug", None) == "owner":
            raise ValidationError("StaffAssignment.role cannot be 'owner'.")

    def __str__(self) -> str:
        scope = "all locations" if self.all_locations else "selected locations"
        return f"{self.membership.user_id} -> {self.role.slug} @ {scope}"


class StaffAssignmentLocation(models.Model):
    assignment = models.ForeignKey(
        StaffAssignment,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="staff_assignment_locations",
    )

    class Meta:
        db_table = "staff_assignment_location"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "branch"],
                name="unique_assignment_branch_location",
            ),
        ]
        indexes = [
            models.Index(fields=["branch"]),
        ]

    def clean(self):
        if self.assignment_id and self.branch_id:
            if self.branch.tenant_id != self.assignment.membership.tenant_id:
                raise ValidationError(
                    "branch must belong to the same tenant as the assignment."
                )

    def __str__(self) -> str:
        return f"{self.assignment_id} -> {self.branch_id}"
