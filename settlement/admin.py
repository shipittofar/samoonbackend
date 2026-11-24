from django.contrib import admin

from .models import OrderSettlement, Payout, PayoutAccount, TenantSettlementTerms


class ReadOnlyAdmin(admin.ModelAdmin):
    """Changes go through the platform console (settlement.services)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TenantSettlementTerms)
class TermsAdmin(ReadOnlyAdmin):
    list_display = ("tenant", "commission_percent", "hold_days", "updated_by", "updated_at")


@admin.register(OrderSettlement)
class OrderSettlementAdmin(ReadOnlyAdmin):
    list_display = ("order", "tenant", "currency", "gross", "commission", "net", "status", "release_after")
    list_filter = ("status", "currency", "via_wallet")


@admin.register(PayoutAccount)
class PayoutAccountAdmin(ReadOnlyAdmin):
    list_display = ("tenant", "kind", "currency", "iban", "address", "status", "is_default")
    list_filter = ("status", "kind")


@admin.register(Payout)
class PayoutAdmin(ReadOnlyAdmin):
    list_display = ("tenant", "amount", "currency", "status", "automatic", "reference", "created_at")
    list_filter = ("status", "currency", "automatic")
