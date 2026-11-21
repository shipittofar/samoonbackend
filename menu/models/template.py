"""Ready-made menus that platform superusers prepare per business type.

Owners see the templates for their business type in the console menu page
and copy one into a branch with one click (categories + items); they then
edit prices and details as usual. A template is never linked to a branch:
applying it copies the content.
"""
import uuid

from django.conf import settings
from django.db import models

from tenants.constants.business_type import BusinessType


class MenuTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    business_type = models.CharField(max_length=30, choices=BusinessType.choices, db_index=True)
    is_active = models.BooleanField(default=True, help_text="Only active templates are offered to owners.")
    # {"categories": [{"name", "description", "items": [{"name", "description",
    #   "price", "preparation_time", "calories"}]}]}  (validated by the API)
    content = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_template"
        ordering = ["business_type", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_business_type_display()})"

    @property
    def categories(self) -> list[dict]:
        return list((self.content or {}).get("categories") or [])

    @property
    def item_count(self) -> int:
        return sum(len(c.get("items") or []) for c in self.categories)
