import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class UserTenantPreference(models.Model):
    """
    Per-user, per-tenant branch preference (last selected / preferred branch).

    Distinct from Branch.is_default (tenant business default) and from
    User.active_branch (current session workspace pointer).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_branch_preferences",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="user_branch_preferences",
    )
    preferred_branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_tenant_preference"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant"],
                name="unique_user_tenant_branch_preference",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "tenant"]),
            models.Index(fields=["tenant"]),
        ]

    def clean(self):
        if self.preferred_branch_id and self.tenant_id:
            if str(self.preferred_branch.tenant_id) != str(self.tenant_id):
                raise ValidationError(
                    {"preferred_branch": "preferred_branch must belong to tenant."}
                )

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.tenant_id} → {self.preferred_branch_id}"
