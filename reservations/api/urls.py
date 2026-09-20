from django.urls import path

from reservations.api.views import (
    ConsolePendingReservationCountView,
    ReservationCancelView,
    ReservationCreateView,
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
