from rest_framework import permissions
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from reservations.api.serializers import (
    AvailableSlotsQuerySerializer,
    ConsoleReservationDetailSerializer,
    ConsoleReservationResponseSerializer,
    ConsoleReservationsQuerySerializer,
    CreateReservationRequestSerializer,
    PendingCountResponseSerializer,
    ReservationResponseSerializer,
    UpdateReservationDurationRequestSerializer,
    UpdateReservationStatusRequestSerializer,
)
from reservations.services import ReservationsBusinessLogicLayer, rules
from superadmin.api.permissions import IsPlatformSuperuser


class CustomerReservationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(
    methods=["GET"],
    tags=["Reservations"],
    summary="My reservations",
    description="The authenticated customer's own reservations at every business, latest first.",
    responses={200: ReservationResponseSerializer(many=True)},
)
@extend_schema(
    methods=["POST"],
    tags=["Reservations"],
    summary="Create reservation",
    description="Create a pending reservation at a branch that has reservations enabled.",
    request=CreateReservationRequestSerializer,
    responses={201: ReservationResponseSerializer},
)
class ReservationCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "reservation_create"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    def get(self, request, *args, **kwargs):
        if "admin" in request.query_params:
            # A business's list is a different, permission-checked resource; never
            # answer it with the caller's personal bookings.
            raise MethodNotAllowed("GET")
        paginator = CustomerReservationPagination()
        rows = paginator.paginate_queryset(
            ReservationsBusinessLogicLayer().list_customer_reservations(customer=request.user), request, view=self
        )
        return paginator.get_paginated_response(ReservationResponseSerializer(rows, many=True).data)

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
    summary="Available times",
    description='Bookable local times ("19:30") of a branch on one day. ?branch_id=&date=&guests=',
    parameters=[AvailableSlotsQuerySerializer],
    responses={200: OpenApiTypes.OBJECT},
)
class AvailableSlotsView(APIView):
    permission_classes = [permissions.AllowAny]

    def perform_authentication(self, request):
        # Public, and never looks at the user: an expired token must not turn it into a 401.
        return

    def get(self, request, *args, **kwargs):
        query = AvailableSlotsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        return Response(
            ReservationsBusinessLogicLayer().get_available_slots(
                branch_id=data["branch_id"], day=data["date"], party_size=data["guests"]
            )
        )


class ConsoleReservationPagination(CustomerReservationPagination):
    page_size = 50


@extend_schema(
    tags=["Reservations - Console"],
    summary="Console reservations",
    description=(
        "Reservations of the branches the caller may view (owner, or staff with "
        "reservations.view). ?branch_id=&date=&status=&search=&page="
    ),
    parameters=[ConsoleReservationsQuerySerializer],
    responses={200: ConsoleReservationResponseSerializer(many=True)},
)
class ConsoleReservationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, tenant_id, *args, **kwargs):
        query = ConsoleReservationsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        qs, counts = ReservationsBusinessLogicLayer().list_console_reservations(
            user=request.user, tenant_id=tenant_id, branch_id=data.get("branch_id"), day=data.get("date"),
            status=data.get("status", ""), search=data.get("search", "").strip(),
        )
        paginator = ConsoleReservationPagination()
        rows = paginator.paginate_queryset(qs, request, view=self)
        response = paginator.get_paginated_response(ConsoleReservationResponseSerializer(rows, many=True).data)
        response.data["counts"] = counts
        return response


@extend_schema(
    tags=["Reservations - Console"],
    summary="Console reservation",
    responses={200: ConsoleReservationDetailSerializer},
)
class ConsoleReservationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, tenant_id, reservation_id, *args, **kwargs):
        reservation = ReservationsBusinessLogicLayer().get_console_reservation(
            user=request.user, tenant_id=tenant_id, reservation_id=reservation_id
        )
        return Response(ConsoleReservationDetailSerializer(reservation).data)


@extend_schema(
    tags=["Reservations - Console"],
    summary="Change one reservation's length",
    description="Shorter, or longer when the time after it is free. reservations.manage at its branch.",
    request=UpdateReservationDurationRequestSerializer,
    responses={200: ConsoleReservationDetailSerializer},
)
class ReservationDurationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, reservation_id, *args, **kwargs):
        serializer = UpdateReservationDurationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = ReservationsBusinessLogicLayer().update_reservation_duration(
            user=request.user, reservation_id=reservation_id, minutes=serializer.validated_data["duration_minutes"]
        )
        return Response(ConsoleReservationDetailSerializer(reservation).data)


@extend_schema(tags=["Reservations - Console"], responses={200: OpenApiTypes.OBJECT})
class BranchReservationRulesView(APIView):
    """A branch's reservation rules. GET: reservations.view. PUT: settings.manage
    or branches.manage; an empty field goes back to the inherited value."""

    permission_classes = [permissions.IsAuthenticated]

    def _branch(self, request, tenant_id, branch_id, *, edit):
        return ReservationsBusinessLogicLayer().authorize_rules(
            user=request.user, tenant_id=tenant_id, branch_id=branch_id, edit=edit
        )

    def get(self, request, tenant_id, branch_id, *args, **kwargs):
        return Response(rules.branch_view(self._branch(request, tenant_id, branch_id, edit=False)))

    def put(self, request, tenant_id, branch_id, *args, **kwargs):
        branch = self._branch(request, tenant_id, branch_id, edit=True)
        return Response(rules.save_branch_rules(branch, request.data, actor=request.user))


@extend_schema(tags=["Reservations - Platform"], responses={200: OpenApiTypes.OBJECT})
class PlatformReservationRulesView(APIView):
    """Platform defaults: for every business, and per business type."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request, *args, **kwargs):
        return Response(rules.admin_view())

    def put(self, request, *args, **kwargs):
        return Response(rules.save_platform_rules(request.data, actor=request.user))


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
