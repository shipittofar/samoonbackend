from django.contrib import admin

from .models import Currency, CurrencyRateChange


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "rate", "is_base", "enabled", "rate_updated_at")
    list_filter = ("enabled", "is_base")
    readonly_fields = ("rate_updated_at", "rate_updated_by")


@admin.register(CurrencyRateChange)
class CurrencyRateChangeAdmin(admin.ModelAdmin):
    list_display = ("currency", "previous_rate", "new_rate", "changed_by", "changed_at", "reason")
    list_filter = ("currency",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
