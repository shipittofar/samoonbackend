from django.contrib import admin

from menu.models import MenuTemplate


@admin.register(MenuTemplate)
class MenuTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "business_type", "is_active", "item_count", "updated_at"]
    list_filter = ["business_type", "is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_by", "created_at", "updated_at"]
