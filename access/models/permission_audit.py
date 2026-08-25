import uuid

from django.conf import settings
from django.db import models


class PermissionAuditAction(models.TextChoices):
    ROLE_CREATED = "role.created", "Role created"
    ROLE_UPDATED = "role.updated", "Role updated"
    ROLE_DELETED = "role.deleted", "Role deleted"
    ASSIGNMENT_CREATED = "assignment.created", "Assignment created"
    ASSIGNMENT_UPDATED = "assignment.updated", "Assignment updated"
    ASSIGNMENT_REVOKED = "assignment.revoked", "Assignment revoked"
    OVERRIDE_CREATED = "override.created", "Override created"
    OVERRIDE_UPDATED = "override.updated", "Override updated"
    OVERRIDE_REMOVED = "override.removed", "Override removed"
    ROLE_PERMISSIONS_CHANGED = "role.permissions_changed", "Role permissions changed"
    OWNERSHIP_TRANSFERRED = "ownership.transferred", "Ownership transferred"


class PermissionAudit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="permission_audit_actions",
        null=True,
        blank=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="permission_audit_entries",
        null=True,
        blank=True,
    )
    membership = models.ForeignKey(
        "access.StaffMembership",
        on_delete=models.SET_NULL,
        related_name="permission_audit_entries",
        null=True,
        blank=True,
    )
    assignment = models.ForeignKey(
        "access.StaffAssignment",
        on_delete=models.SET_NULL,
        related_name="permission_audit_entries",
        null=True,
        blank=True,
    )
    permission = models.ForeignKey(
        "access.Permission",
        on_delete=models.SET_NULL,
        related_name="permission_audit_entries",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=64, choices=PermissionAuditAction.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "permission_audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at}"
