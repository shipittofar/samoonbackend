from django.urls import path

from addresses.api.views import (
    AddressDetailView,
    AddressListCreateView,
    AddressRestoreView,
    AddressSetDefaultView,
)
from addresses.api.views.serviceability import (
    AddressBranchView,
    AddressServiceabilityView,
    AddressSuggestionsView,
    CheckServiceabilityView,
)

app_name = "addresses"

urlpatterns = [
    path("suggestions/", AddressSuggestionsView.as_view(), name="address-suggestions"),
    path(
        "check-serviceability/",
        CheckServiceabilityView.as_view(),
        name="address-check-serviceability",
    ),
    path("", AddressListCreateView.as_view(), name="address-list-create"),
    path(
        "<uuid:address_id>/serviceability/",
        AddressServiceabilityView.as_view(),
        name="address-serviceability",
    ),
    path(
        "<uuid:address_id>/branch/",
        AddressBranchView.as_view(),
        name="address-branch",
    ),
    path("<uuid:address_id>/", AddressDetailView.as_view(), name="address-detail"),
    path(
        "<uuid:address_id>/set-default/",
        AddressSetDefaultView.as_view(),
        name="address-set-default",
    ),
    path(
        "<uuid:address_id>/restore/",
        AddressRestoreView.as_view(),
        name="address-restore",
    ),
]
