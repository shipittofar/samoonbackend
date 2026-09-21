# apps/orders/admin.py
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from orders.models import (
    Order,
    OrderDeliveryAddress,
    OrderItem,
    OrderItemExtra,
    OrderStatusHistory,
)


class OrderItemExtraInline(admin.TabularInline):
    model = OrderItemExtra
    extra = 0
    fields = ("extra", "price")
    autocomplete_fields = ("extra",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("menu_item", "name", "image", "quantity", "unit_price", "total_price", "notes")
    readonly_fields = ("total_price",)
    autocomplete_fields = ("menu_item",)
    show_change_link = True


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    fields = ("status", "timestamp", "note")
    readonly_fields = ("timestamp",)
    ordering = ("-timestamp",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer",
        "branch",
        "order_type",
        "status",
        "payment_status",
        "total",
        "item_count",
        "created_at",
    )
    list_filter = ("status", "payment_status", "payment_method", "order_type", "branch")
    search_fields = (
        "order_number",
        "id",
        "customer__phone_number",
        "customer__email",
        "branch__name",
    )
    autocomplete_fields = ("customer", "branch", "delivery_address")
    readonly_fields = ("id", "order_number", "created_at", "updated_at")
    list_select_related = ("customer", "branch")
    inlines = (OrderItemInline, OrderStatusHistoryInline)
    actions = ["cancel_selected_orders"]
    fieldsets = (
        (None, {"fields": ("id", "order_number", "customer", "branch")}),
        (
            _("Order details"),
            {"fields": ("order_type", "status", "table_number", "estimated_time", "notes")},
        ),
        (
            _("Payment"),
            {"fields": ("payment_method", "payment_status")},
        ),
        (
            _("Delivery"),
            {"fields": ("delivery_address",)},
        ),
        (
            _("Amounts"),
            {
                "fields": (
                    "subtotal",
                    "discount_amount",
                    "discount_code",
                    "tax",
                    "service_charge",
                    "total",
                )
            },
        ),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description=_("Items"))
    def item_count(self, obj):
        return obj.items.count()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description=_("Cancel selected orders"))
    def cancel_selected_orders(self, request, queryset):
        from core.exceptions import OrderNotCancellableException
        from orders.services.orders_bll import OrdersBusinessLogicLayer

        bll = OrdersBusinessLogicLayer()
        for order in queryset:
            try:
                bll.admin_cancel_order(order=order)
            except OrderNotCancellableException:
                self.message_user(
                    request,
                    f"Order {order.order_number} cannot be cancelled.",
                    level="warning",
                )


@admin.register(OrderDeliveryAddress)
class OrderDeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ("street", "city", "province", "country", "created_at")
    search_fields = ("street", "city", "postal_code", "phone", "first_name", "last_name")
    readonly_fields = ("id", "source_address_id", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "name", "menu_item", "quantity", "unit_price", "total_price")
    list_filter = ("order__status",)
    search_fields = ("name", "order__order_number", "menu_item__name")
    autocomplete_fields = ("order", "menu_item")
    readonly_fields = ("total_price",)
    list_select_related = ("order", "menu_item")
    inlines = (OrderItemExtraInline,)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItemExtra)
class OrderItemExtraAdmin(admin.ModelAdmin):
    list_display = ("order_item", "extra", "price")
    search_fields = ("order_item__name", "extra__name")
    autocomplete_fields = ("order_item", "extra")
    list_select_related = ("order_item", "extra")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "timestamp")
    list_filter = ("status",)
    search_fields = ("order__order_number",)
    autocomplete_fields = ("order",)
    readonly_fields = ("timestamp",)
    ordering = ("-timestamp",)

    def has_delete_permission(self, request, obj=None):
        return False
