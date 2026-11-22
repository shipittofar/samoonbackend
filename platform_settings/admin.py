from django.contrib import admin

from .models import PlatformSetting, PlatformSettingChange


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")
    search_fields = ("key",)


@admin.register(PlatformSettingChange)
class PlatformSettingChangeAdmin(admin.ModelAdmin):
    list_display = ("key", "changed_at", "changed_by", "reason")
    list_filter = ("changed_at",)
    search_fields = ("key", "reason")
    readonly_fields = ("key", "previous_value", "new_value", "reason", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
