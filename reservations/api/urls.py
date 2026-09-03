from django.urls import path

from reservations.api.views import (
    ConsolePendingReservationCountView,
    ReservationCancelView,
    ReservationCreateView,
    ReservationStatusUpdateView,
)

app_name = "reservations"

urlpatterns = [
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
