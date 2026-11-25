from django.urls import path

from reservations.api.views import (
    AvailableSlotsView,
    BranchReservationRulesView,
    ConsoleReservationDetailView,
    ConsoleReservationListView,
    ConsolePendingReservationCountView,
    ReservationCancelView,
    PlatformReservationRulesView,
    ReservationCreateView,
    ReservationDurationView,
    ReservationStatusUpdateView,
)
from tenants.api.views.qr_manage import (
    ReservationQrDisableAPIView,
    ReservationQrEnableAPIView,
    ReservationQrRegenerateAPIView,
    ReservationQrRetrieveAPIView,
)

app_name = "reservations"

urlpatterns = [
    path(
        "branches/<uuid:branch_id>/qr/",
        ReservationQrRetrieveAPIView.as_view(),
        name="reservation-branch-qr",
    ),
    path(
        "branches/<uuid:branch_id>/qr/enable/",
        ReservationQrEnableAPIView.as_view(),
        name="reservation-branch-qr-enable",
    ),
    path(
        "branches/<uuid:branch_id>/qr/disable/",
        ReservationQrDisableAPIView.as_view(),
        name="reservation-branch-qr-disable",
    ),
    path(
        "branches/<uuid:branch_id>/qr/regenerate/",
        ReservationQrRegenerateAPIView.as_view(),
        name="reservation-branch-qr-regenerate",
    ),
    path("", ReservationCreateView.as_view(), name="reservation-create"),
    path("platform-rules/", PlatformReservationRulesView.as_view(), name="platform-rules"),
    path(
        "console-reservations/tenants/<uuid:tenant_id>/branches/<uuid:branch_id>/rules/",
        BranchReservationRulesView.as_view(),
        name="branch-rules",
    ),
    path("<uuid:reservation_id>/duration/", ReservationDurationView.as_view(), name="reservation-duration"),
    path("available-slots/", AvailableSlotsView.as_view(), name="available-slots"),
    path(
        "console-reservations/tenants/<uuid:tenant_id>/",
        ConsoleReservationListView.as_view(),
        name="console-reservation-list",
    ),
    path(
        "console-reservations/tenants/<uuid:tenant_id>/<uuid:reservation_id>/",
        ConsoleReservationDetailView.as_view(),
        name="console-reservation-detail",
    ),
    path(
        "<uuid:reservation_id>/cancel/",
        ReservationCancelView.as_view(),
        name="reservation-cancel",
    ),
    path(
        "<uuid:reservation_id>/status/",
        ReservationStatusUpdateView.as_view(),
        name="reservation-status-update",
    ),
    path(
        "console-reservations/tenants/<uuid:tenant_id>/branches/<uuid:branch_id>/pending-count/",
        ConsolePendingReservationCountView.as_view(),
        name="console-reservation-pending-count",
    ),
]
