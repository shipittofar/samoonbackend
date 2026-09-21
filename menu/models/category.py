from django.db import models
import uuid

from core.utils.slug import assign_unique_slug
from core.models import WebPImageMixin


class MenuCategory(WebPImageMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="categories",
    )

    name = models.CharField(max_length=255)

    slug = models.SlugField(
        max_length=255,
        blank=True,
        unique=True,
    )

    description = models.TextField(
        blank=True
    )

    image = models.ImageField(
        upload_to="menu_categories/",
        blank=True,
        null=True,
    )
    image_asset = models.ForeignKey(
        "uploads.UploadAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    sort_order = models.PositiveIntegerField(
        default=0
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def save(self, *args, **kwargs):
        assign_unique_slug(self, MenuCategory)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["sort_order"]
        db_table = "menu_category"

        verbose_name = "Category"
        verbose_name_plural = "Categories"
