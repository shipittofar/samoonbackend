from django.contrib import admin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("type", "recipient", "tenant", "status", "priority", "created_at")
    list_filter = ("category", "status", "priority", "type")
    search_fields = ("recipient__phone_number", "recipient__email", "type")
    raw_id_fields = ("recipient", "tenant", "branch", "actor")
    readonly_fields = ("created_at", "read_at", "archived_at")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "category", "enabled", "min_priority")
    raw_id_fields = ("user", "tenant")
