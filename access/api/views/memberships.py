from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from access.api.serializers.request import (
    StaffAssignmentCreateSerializer,
    StaffAssignmentUpdateSerializer,
    StaffMembershipCreateSerializer,
    StaffMembershipUpdateSerializer,
    SwitchActiveTenantInputSerializer,
    SwitchActiveBranchInputSerializer,
)
from access.api.serializers.response import StaffAssignmentSerializer, StaffMembershipSerializer
from access.authorization import RequirePermission
from core.exceptions import StaffAssignmentNotFoundException, StaffMembershipNotFoundException
from access.selectors import staff_selector
from access.services.membership_bll import membership_service


class StaffConsolePagination(PageNumberPagination):
    """Bounded client page_size for /console/staff roster endpoints."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 500


@extend_schema(
    tags=["Access - Staff Membership"],
    summary="List or add staff memberships",
    description="Returns all staff memberships for a tenant or invites a new staff member."
)
class StaffMembershipListCreateView(ListCreateAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    pagination_class = StaffConsolePagination

    def get_queryset(self):
        return staff_selector.get_membership_queryset(tenant_id=self.kwargs["tenant_id"])

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StaffMembershipCreateSerializer
        return StaffMembershipSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = membership_service.create_membership(
            tenant_id=kwargs["tenant_id"],
            user_id=serializer.validated_data["user"].id,
            invited_by_id=request.user.id,
            status=serializer.validated_data.get("status", "pending"),
        )

        return Response(StaffMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Access - Staff Membership"],
    summary="Retrieve or update staff membership",
    description="Returns details of a staff membership or updates its status and information."
)
class StaffMembershipRetrieveUpdateView(RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    lookup_url_kwarg = "membership_id"

    def get_object(self):
        membership = staff_selector.get_membership_by_id(
            tenant_id=self.kwargs["tenant_id"], membership_id=self.kwargs[self.lookup_url_kwarg]
        )
        if membership is None:
            raise StaffMembershipNotFoundException()
        return membership

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return StaffMembershipUpdateSerializer
        return StaffMembershipSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        membership = membership_service.update_membership(
            tenant_id=self.kwargs["tenant_id"],
            membership_id=instance.id,
            **serializer.validated_data,
        )

        return Response(StaffMembershipSerializer(membership).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Access - Staff Membership"],
    summary="Remove staff membership",
    description="Soft-removes a staff member from the tenant by changing the membership status to 'removed'."
)
class StaffMembershipRemoveView(GenericAPIView):
    # Soft-removal: sets status to "removed", the row itself is kept.
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = StaffMembershipSerializer
    lookup_url_kwarg = "membership_id"

    def delete(self, request, *args, **kwargs):
        membership = membership_service.remove_membership(
            tenant_id=kwargs["tenant_id"], membership_id=kwargs[self.lookup_url_kwarg]
        )
        return Response(StaffMembershipSerializer(membership).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Access - Staff Assignment"],
    summary="List or create staff role assignments",
    description=(
        "Creates a canonical role grant scoped by location_ids and/or all_locations. "
        "One assignment row represents one role grant; multiple locations use the "
        "StaffAssignmentLocation junction."
    ),
)
class StaffAssignmentListCreateView(ListCreateAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    pagination_class = StaffConsolePagination

    def get_queryset(self):
        return staff_selector.get_assignment_queryset(
            tenant_id=self.kwargs["tenant_id"],
            membership_id=self.request.query_params.get("membership_id"),
            user_id=self.request.query_params.get("user_id"),
            viewer=self.request.user,
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StaffAssignmentCreateSerializer
        return StaffAssignmentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={"tenant_id": kwargs["tenant_id"], "request": request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        assignment = membership_service.create_assignment(
            membership_id=data["membership_id"],
            role_id=data["role_id"],
            location_ids=data["location_ids"],
            all_locations=data["all_locations"],
            mode=data.get("mode"),
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            granted_by_id=request.user.id,
        )

        return Response(
            StaffAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Access - Staff Assignment"],
    summary="Retrieve, update, or revoke a staff role assignment",
    description=(
        "GET returns the canonical assignment contract. PUT/PATCH update scope and metadata "
        "through assignment_bll. DELETE soft-revokes the assignment (status=revoked)."
    ),
)
class StaffAssignmentRetrieveUpdateDestroyView(RetrieveAPIView, GenericAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = StaffAssignmentSerializer
    lookup_url_kwarg = "assignment_id"

    def get_object(self):
        assignment = staff_selector.get_assignment_by_id(
            tenant_id=self.kwargs["tenant_id"],
            assignment_id=self.kwargs[self.lookup_url_kwarg],
            viewer=self.request.user,
        )
        if assignment is None:
            raise StaffAssignmentNotFoundException()
        return assignment

    def put(self, request, *args, **kwargs):
        return self._update(request, partial=False)

    def patch(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def _update(self, request, *, partial: bool):
        instance = self.get_object()
        serializer = StaffAssignmentUpdateSerializer(
            data=request.data,
            partial=partial,
            context={"assignment": instance, "request": request},
        )
        serializer.is_valid(raise_exception=True)

        assignment = membership_service.update_assignment(
            tenant_id=self.kwargs["tenant_id"],
            assignment_id=instance.id,
            updated_by_id=request.user.id,
            **serializer.validated_data,
        )
        return Response(StaffAssignmentSerializer(assignment).data, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        assignment = membership_service.revoke_assignment(
            tenant_id=self.kwargs["tenant_id"],
            assignment_id=instance.id,
            revoked_by_id=request.user.id,
        )
        return Response(StaffAssignmentSerializer(assignment).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Access - Staff Membership"],
    summary="Switch active tenant",
    description="Switches the authenticated user's active tenant."
)
class SwitchActiveTenantAPIView(GenericAPIView):
    serializer_class = SwitchActiveTenantInputSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership_service.switch_active_tenant(
            user=request.user,
            tenant_id=serializer.validated_data["tenantId"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Access - Staff Membership"],
    summary="Switch active branch",
    description="Switches the authenticated user's active branch within their active tenant.",
)
class SwitchActiveBranchAPIView(GenericAPIView):
    serializer_class = SwitchActiveBranchInputSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership_service.switch_active_branch(
            user=request.user,
            branch_id=serializer.validated_data["branchId"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)