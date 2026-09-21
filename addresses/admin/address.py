from django.contrib import admin

from addresses.models import Address, AddressAuditLog


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "address_type",
        "user",
        "city",
        "province",
        "country",
        "is_default",
        "verification_status",
        "deleted_at",
    )
    list_filter = ("is_default", "verification_status", "address_type", "country", "deleted_at")
    search_fields = (
        "title",
        "formatted_address",
        "street",
        "district",
        "city",
        "postal_code",
        "user__phone_number",
        "user__email",
        "first_name",
        "last_name",
    )
    autocomplete_fields = ("user", "verified_by")
    list_select_related = ("user", "verified_by")
    readonly_fields = ("id", "uuid", "legacy_id", "fingerprint", "formatted_address", "created_at", "updated_at")

    def get_queryset(self, request):
        return Address.all_objects.all()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AddressAuditLog)
class AddressAuditLogAdmin(admin.ModelAdmin):
    list_display = ("address", "action", "actor", "user", "created_at")
    list_filter = ("action",)
    search_fields = ("address__title", "address__street", "user__email")
    readonly_fields = ("id", "created_at")
    list_select_related = ("address", "actor", "user")

    def has_delete_permission(self, request, obj=None):
        return False
