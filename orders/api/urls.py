# orders/urls.py
from django.urls import path

from addresses.api.views.legacy import (
    LegacyAddressDetailView,
    LegacyAddressListCreateView,
)
from orders.api.views import (
    ConsoleOrderListView,
    ConsolePendingOrderCountView,
    ConsoleTenantCustomersListView,
    ConsoleTenantOrdersListView,
    OrderCancelView,
    OrderDetailView,
    OrderListCreateView,
    OrderStatusUpdateView,
    ValidateDiscountView,
)

app_name = "orders"

urlpatterns = [
    path(
        "",
        OrderListCreateView.as_view(),
        name="order-list-create"
    ),
    path(
        "validate-discount/",
        ValidateDiscountView.as_view(),
        name="order-validate-discount",
    ),
    path(
        "addresses/",
        LegacyAddressListCreateView.as_view(),
        name="address-list-create"
    ),
    path(
        "addresses/<int:address_id>/",
        LegacyAddressDetailView.as_view(),
        name="address-detail"
    ),
    path(
        "<uuid:public_id>/",
        OrderDetailView.as_view(),
        name="order-detail"
    ),
    path(
        "<uuid:public_id>/cancel/",
        OrderCancelView.as_view(),
        name="order-cancel",
    ),
    path(
        "<uuid:public_id>/status/",
        OrderStatusUpdateView.as_view(),
        name="order-status-update",
    ),
    # Console APIs
    path(
        "console-orders/tenants/<uuid:tenant_id>/customers/",
        ConsoleTenantCustomersListView.as_view(),
        name="console-customer-tenant-list",
    ),
    path(
        "console-orders/tenants/<uuid:tenant_id>/branches/",
        ConsoleTenantOrdersListView.as_view(),
        name="console-order-tenant-list",
    ),
    path(
        "console-orders/tenants/<uuid:tenant_id>/branches/<uuid:branch_id>/pending-count/",
        ConsolePendingOrderCountView.as_view(),
        name="console-order-pending-count",
    ),
    path(
        "console-orders/tenants/<uuid:tenant_id>/branches/<uuid:branch_id>/",
        ConsoleOrderListView.as_view(),
        name="console-order-list",
    ),
]
