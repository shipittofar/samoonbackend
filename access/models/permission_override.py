import uuid

from django.conf import settings
from django.db import models


class PermissionOverrideEffect(models.TextChoices):
    ALLOW = "allow", "Allow"
    DENY = "deny", "Deny"


class PermissionOverride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    membership = models.ForeignKey(
        "access.StaffMembership",
        on_delete=models.CASCADE,
        related_name="permission_overrides",
    )
    permission = models.ForeignKey(
        "access.Permission",
        on_delete=models.CASCADE,
        related_name="permission_overrides",
    )
    effect = models.CharField(
        max_length=10,
        choices=PermissionOverrideEffect.choices,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_permission_overrides",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "permission_override"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "permission"],
                name="unique_membership_permission_override",
            ),
        ]
        indexes = [
            models.Index(fields=["membership"]),
            models.Index(fields=["permission"]),
        ]

    def __str__(self) -> str:
        return f"{self.membership_id} -> {self.permission.slug} ({self.effect})"
