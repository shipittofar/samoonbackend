"""Unused duplicate Tenant admin. Canonical registration is tenants.admin.tenant.

Do not import this module — it would double-register Tenant.
"""
from django.contrib import admin
from django.utils.html import format_html

from tenants.models import Tenant, WorkingHour


class WorkingHourInline(admin.TabularInline):
    model = WorkingHour
    extra = 0
    max_num = 7
    ordering = ("day",)
    fields = ("day", "open_time", "close_time", "is_closed")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "slug",
        "image_preview",
        "owner",
        "city",
        "phone",
        "business_types",
        "status",
        "is_active",
        "updated_at",
        "created_at",
    )

    search_fields = (
        "name",
        "slug",
        "phone",
        "city",
        "owner__phone_number",
    )

    list_filter = (
        "status",
        "business_types",
        "is_active",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    autocomplete_fields = (
        "owner",
    )

    readonly_fields = (
        "slug",
        "image_preview",
        "updated_at",
        "created_at",
    )

    inlines = (
        WorkingHourInline,
    )

    @admin.display(description="Image")
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="70" height="70" style="object-fit:cover;border-radius:6px;" />',
                obj.image.url,
            )
        return "-"

@admin.register(WorkingHour)
class WorkingHourAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "get_day_display",
        "open_time",
        "close_time",
        "is_closed",
    )

    list_filter = (
        "day",
        "is_closed",
    )

    search_fields = (
        "tenant__name",
    )

    autocomplete_fields = (
        "tenant",
    )

    ordering = (
        "tenant",
        "day",
    )

    @admin.display(description="Day")
    def get_day_display(self, obj: WorkingHour) -> str:
        return obj.get_day_display()