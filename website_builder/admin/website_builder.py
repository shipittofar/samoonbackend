from django.contrib import admin

from website_builder.models import BranchWebsiteOverride, WebsiteLayout


@admin.register(WebsiteLayout)
class WebsiteLayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "status", "last_saved_at", "last_published_at", "updated_at")
    search_fields = ("tenant__name", "tenant__slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BranchWebsiteOverride)
class BranchWebsiteOverrideAdmin(admin.ModelAdmin):
    list_display = ("id", "website_layout", "branch", "updated_at")
    search_fields = ("branch__name", "branch__slug", "website_layout__tenant__name")
