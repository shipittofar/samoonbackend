from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from reservations.api.serializers import (
    CreateReservationRequestSerializer,
    PendingCountResponseSerializer,
    ReservationResponseSerializer,
    UpdateReservationStatusRequestSerializer,
)
from reservations.services import ReservationsBusinessLogicLayer


@extend_schema(
    tags=["Reservations"],
    summary="Create reservation",
    description="Create a pending reservation at a branch that has reservations enabled.",
    request=CreateReservationRequestSerializer,
    responses={201: ReservationResponseSerializer},
)
class ReservationCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = CreateReservationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = ReservationsBusinessLogicLayer().create_reservation(
            customer=request.user,
            validated_data=dict(serializer.validated_data),
        )
        return Response(ReservationResponseSerializer(reservation).data, status=201)


@extend_schema(
    tags=["Reservations"],
    summary="Cancel reservation",
    description="Cancel a pending or confirmed reservation owned by the authenticated customer.",
    responses={200: ReservationResponseSerializer},
)
class ReservationCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, reservation_id, *args, **kwargs):
        reservation = ReservationsBusinessLogicLayer().cancel_reservation(
            customer=request.user,
            reservation_id=reservation_id,
        )
        return Response(ReservationResponseSerializer(reservation).data)


@extend_schema(
    tags=["Reservations - Console"],
    summary="Update reservation status",
    description=(
        "Update reservation status. Restricted to the tenant owner or staff "
        "with reservations.manage at the reservation's branch."
    ),
    request=UpdateReservationStatusRequestSerializer,
    responses={200: ReservationResponseSerializer},
)
class ReservationStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, reservation_id, *args, **kwargs):
        serializer = UpdateReservationStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = ReservationsBusinessLogicLayer().update_reservation_status(
            user=request.user,
            reservation_id=reservation_id,
            new_status=serializer.validated_data["status"],
        )
        return Response(ReservationResponseSerializer(reservation).data)


@extend_schema(
    tags=["Reservations - Console"],
    summary="Console pending reservation count",
    description=(
        "Authoritative pending-reservation count for a tenant branch. "
        "Restricted to the tenant owner or staff with reservations.view "
        "at that branch. There is no unscoped admin list. "
        "Pending means status='pending' only."
    ),
    responses={200: PendingCountResponseSerializer},
)
class ConsolePendingReservationCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, tenant_id, branch_id, *args, **kwargs):
        count = ReservationsBusinessLogicLayer().get_pending_reservation_count(
            user=request.user,
            tenant_id=tenant_id,
            branch_id=branch_id,
        )
        return Response(PendingCountResponseSerializer({"count": count}).data)
