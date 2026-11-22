from django.conf import settings
from django.db import models


class PlatformSetting(models.Model):
    """One platform-wide setting: a JSON value under a unique key.

    Keys used so far:
      - ``homepage.hero``: the marketplace home page hero (background images
        and slideshow timing), see services/homepage_hero.py.
      - ``config:<fieldId>``: a platform-level override of one Platform
        Configuration field (frontend src/config), see services/platform_config.py.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key

class PlatformSettingChange(models.Model):
    """Who changed a platform setting, when, from what, to what, and why."""

    key = models.CharField(max_length=100, db_index=True)
    previous_value = models.JSONField(null=True, blank=True)
    # null = the override was removed (back to the built-in default).
    new_value = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    # Set for a business-level change (TenantConfigOverride); empty for platform-wide.
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:
        return f"{self.key} @ {self.changed_at:%Y-%m-%d %H:%M}"


class TenantConfigOverride(models.Model):
    """A business's own value for a tenant-level Platform Configuration field
    (frontend src/config: fields whose inheritance level is "tenant", e.g. the
    default language, currency or theme colours). Edited by the business's
    settings managers; secrets are never stored here."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="config_overrides")
    field_id = models.CharField(max_length=95)
    value = models.JSONField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["tenant_id", "field_id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "field_id"], name="uniq_tenant_config_override"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}: {self.field_id}"
