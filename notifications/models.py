import uuid

from django.conf import settings
from django.db import models


class NotificationStatus(models.TextChoices):
    UNREAD = "unread", "Unread"
    READ = "read", "Read"
    ARCHIVED = "archived", "Archived"
    DELETED = "deleted", "Deleted"


class NotificationPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


class Notification(models.Model):
    """One in-app notification for one user.

    Created only by the server, from real events (notifications.events);
    clients can read, mark, archive and delete their own, never create them.
    The text is rendered per reader language from ``type`` + ``data`` (see
    notifications.catalog), so nothing language-specific is stored.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    # Business context (console notifications); empty for personal ones.
    tenant = models.ForeignKey("tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("tenants.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    type = models.CharField(max_length=50, db_index=True)
    category = models.CharField(max_length=20, db_index=True)
    priority = models.CharField(max_length=10, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL)
    status = models.CharField(max_length=10, choices=NotificationStatus.choices, default=NotificationStatus.UNREAD)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=150, blank=True)
    data = models.JSONField(default=dict, blank=True)
    link_type = models.CharField(max_length=20, blank=True)
    link_id = models.CharField(max_length=64, blank=True)
    link_href = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "status", "-created_at"]),
            models.Index(fields=["recipient", "tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} -> {self.recipient_id}"


class NotificationPreference(models.Model):
    """A user's choice for one category, per business (empty tenant = personal)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    tenant = models.ForeignKey("tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    category = models.CharField(max_length=20)
    enabled = models.BooleanField(default=True)
    channels = models.JSONField(default=dict, blank=True)
    min_priority = models.CharField(max_length=10, choices=NotificationPriority.choices, default=NotificationPriority.LOW)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant", "category"], name="uniq_notification_pref"),
            models.UniqueConstraint(
                fields=["user", "category"],
                condition=models.Q(tenant__isnull=True),
                name="uniq_notification_pref_personal",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.tenant_id or '-'} {self.category}"
