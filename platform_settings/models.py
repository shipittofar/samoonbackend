from django.conf import settings
from django.db import models


class PlatformSetting(models.Model):
    """One platform-wide setting: a JSON value under a unique key.

    Keys used so far:
      - ``homepage.hero``: the marketplace home page hero (background images
        and slideshow timing), see services/homepage_hero.py.
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
