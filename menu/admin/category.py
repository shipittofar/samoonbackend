from django.contrib import admin
from django.utils.html import format_html

from menu.models import MenuCategory


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "branch",
        "sort_order",
        "item_count",
        "image_preview",
        "created_at",
    )

    list_display_links = ("id", "name")

    list_editable = ("sort_order",)

    search_fields = (
        "name",
        "slug",
    )

    list_filter = (
        "branch",
    )

    ordering = (
        "sort_order",
    )

    readonly_fields = (
        "slug",
        "image_preview",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {
            "fields": ("branch", "name", "slug", "description", "sort_order")
        }),
        ("Image", {
            "fields": ("image", "image_preview")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = "Items"

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 80px; border-radius: 4px;" />',
                obj.image.url,
            )
        return "-"
    image_preview.short_description = "Preview"