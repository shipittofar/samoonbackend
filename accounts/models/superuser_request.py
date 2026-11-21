"""Platform superusers: how a new one is added.

The first superuser is created directly by ``manage.py admin_add`` (there is
nobody to approve it). After that, ``admin_add`` only works while an existing
superuser has switched on ``PlatformSecuritySettings.allow_superuser_requests``
in the Django admin, and it creates a *pending* request. The account becomes a
superuser only when another superuser approves the request in the Django admin.
Every decision is recorded (who, when).
"""
import uuid

from django.conf import settings
from django.db import models


class PlatformSecuritySettings(models.Model):
    """Singleton (pk=1), edited by superusers in the Django admin."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    allow_superuser_requests = models.BooleanField(
        default=False,
        help_text=(
            "While on, `samoon admin-add` (manage.py admin_add) may file new superuser "
            "requests. Each one still needs approval by a superuser. Leave off otherwise."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "platform_security_settings"
        verbose_name = "Platform security settings"
        verbose_name_plural = "Platform security settings"

    def __str__(self) -> str:
        return "Platform security settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "PlatformSecuritySettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SuperuserRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class SuperuserRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="superuser_requests",
    )
    status = models.CharField(
        max_length=16,
        choices=SuperuserRequestStatus.choices,
        default=SuperuserRequestStatus.PENDING,
        db_index=True,
    )
    note = models.CharField(max_length=255, blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "superuser_requests"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="one_pending_superuser_request_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} ({self.get_status_display()})"
