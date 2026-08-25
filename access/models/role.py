import uuid

from django.db import models


class RoleSlug(models.TextChoices):
    """Matches docs/08_FINAL_DBML_CORRECTION.dbml's role_slug enum exactly.
    "owner" exists here for schema/reference completeness only — Owner is
    a business entity (places.Owner), never a StaffMembership row. See
    StaffMembership.clean()."""
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    CASHIER = "cashier", "Cashier"
    WAITER = "waiter", "Waiter"
    KITCHEN = "kitchen", "Kitchen"
    MARKETING = "marketing", "Marketing"
    SUPPORT = "support", "Support"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    slug = models.CharField(max_length=20, choices=RoleSlug.choices, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    system_role = models.BooleanField(
        default=True,
        help_text="True for the 8 seeded, code-owned roles. Custom (non-system) "
                   "roles are not implemented in this epic.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "role"
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.name} - {self.slug}"
