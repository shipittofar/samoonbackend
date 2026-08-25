import uuid

from django.db import models


class Permission(models.Model):
    """resource.action pairs, e.g. "menu.manage". Scoped to resources that
    actually exist in this backend today (branches, menu, orders, staff) —
    see docs/19_EPIC_006_IMPLEMENTATION_REPORT.md for why permissions for
    not-yet-built features (loyalty, payments, reservations, ...) are
    deliberately not seeded here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    resource = models.CharField(max_length=50)
    action = models.CharField(max_length=50)
    slug = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "permission"
        ordering = ["resource", "action"]
        indexes = [
            models.Index(fields=["resource"]),
        ]

    def __str__(self) -> str:
        return self.slug


class RolePermission(models.Model):
    role = models.ForeignKey(
        "access.Role",
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        "access.Permission",
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    class Meta:
        db_table = "role_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="unique_role_permission"
            ),
        ]
        indexes = [
            models.Index(fields=["permission"]),
        ]

    def __str__(self) -> str:
        return f"{self.role.slug} -> {self.permission.slug}"
