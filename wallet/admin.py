from django.contrib import admin

from .models import LedgerEntry, LedgerTransaction, TopUp, WalletAccount


class ReadOnlyAdmin(admin.ModelAdmin):
    """The ledger is append-only: changes go through wallet.services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletAccount)
class WalletAccountAdmin(ReadOnlyAdmin):
    list_display = ("kind", "user", "tenant", "currency", "balance", "is_frozen")
    list_filter = ("kind", "currency", "is_frozen")
    search_fields = ("user__phone_number", "user__email", "tenant__name")


class EntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    readonly_fields = ("account", "amount", "balance_after", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(ReadOnlyAdmin):
    list_display = ("kind", "currency", "order", "created_by", "created_at", "description")
    list_filter = ("kind", "currency")
    search_fields = ("idempotency_key", "description")
    inlines = [EntryInline]


@admin.register(TopUp)
class TopUpAdmin(ReadOnlyAdmin):
    """Review happens in the platform console (approve / reject)."""

    list_display = ("order_number", "user", "provider", "amount", "currency", "status", "verified", "created_at")
    list_filter = ("status", "provider", "currency", "method")
    search_fields = ("order_number", "gateway_ref", "receipt_ref", "user__phone_number", "user__email")
