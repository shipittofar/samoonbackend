from uuid import UUID

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from addresses.api.permissions import IsAddressOwnerOrReadOnlyStaff
from addresses.api.serializers.request.serviceability import CheckServiceabilityRequestSerializer
from addresses.api.serializers.response.serviceability import (
    AddressSuggestionsResponseSerializer,
    BranchResolutionResponseSerializer,
    ServiceabilityResponseSerializer,
)
from addresses.api.throttling import AddressReadThrottle
from addresses.services.address_domain_service import AddressDomainService


def _parse_uuid(value: str) -> UUID:
    return UUID(str(value))


class AddressServiceabilityView(APIView):
    permission_classes = [IsAuthenticated, IsAddressOwnerOrReadOnlyStaff]
    throttle_classes = [AddressReadThrottle]

    @extend_schema(
        tags=["Users - Addresses"],
        summary="Check address serviceability",
        description="Validate whether a saved address can receive delivery from a branch.",
        parameters=[
            OpenApiParameter("branch_id", UUID, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: ServiceabilityResponseSerializer},
        examples=[
            OpenApiExample(
                "Serviceable",
                value={
                    "serviceable": True,
                    "delivery_zone": "branch:uuid",
                    "assigned_branch": {"id": "uuid", "name": "Main"},
                    "delivery_fee": "3.25",
                    "estimated_delivery_time": 28,
                    "distance": 1.5,
                    "minimum_order": "10.00",
                    "currency": "USD",
                    "reason": None,
                },
                response_only=True,
            ),
        ],
    )
    def get(self, request, address_id):
        domain = AddressDomainService()
        address = domain.get_address(request.user, address_id)
        self.check_object_permissions(request, address)
        branch = domain.resolve_branch(
            request.user, _parse_uuid(request.query_params["branch_id"])
        )
        result = domain.evaluate_serviceability(
            user=request.user,
            branch=branch,
            delivery_data={"address_id": str(address_id)},
        )
        return Response(ServiceabilityResponseSerializer(result.to_dict()).data)


class CheckServiceabilityView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AddressReadThrottle]

    @extend_schema(
        tags=["Users - Addresses"],
        summary="Check serviceability for address_id or inline delivery_address",
        request=CheckServiceabilityRequestSerializer,
        responses={200: ServiceabilityResponseSerializer},
        examples=[
            OpenApiExample(
                "By address_id",
                value={
                    "branch_id": "00000000-0000-0000-0000-000000000001",
                    "address_id": "00000000-0000-0000-0000-000000000002",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Inline delivery_address",
                value={
                    "branch_id": "00000000-0000-0000-0000-000000000001",
                    "delivery_address": {
                        "street": "123 Main St",
                        "city": "Los Angeles",
                        "zip": "90001",
                        "lat": 34.0522,
                        "lng": -118.2437,
                    },
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = CheckServiceabilityRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = AddressDomainService().resolve_branch(request.user, data["branch_id"])

        delivery_data: dict = {"branch_id": str(data["branch_id"])}
        if data.get("address_id"):
            delivery_data["address_id"] = data["address_id"]
        else:
            delivery_data.update(data.get("delivery_address") or {})

        result = AddressDomainService().evaluate_serviceability(
            user=request.user,
            branch=branch,
            delivery_data=delivery_data,
        )
        return Response(ServiceabilityResponseSerializer(result.to_dict()).data)


class AddressBranchView(APIView):
    permission_classes = [IsAuthenticated, IsAddressOwnerOrReadOnlyStaff]
    throttle_classes = [AddressReadThrottle]

    @extend_schema(
        tags=["Users - Addresses"],
        summary="Resolve branch for address",
        parameters=[
            OpenApiParameter("branch_id", UUID, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: BranchResolutionResponseSerializer},
    )
    def get(self, request, address_id):
        domain = AddressDomainService()
        address = domain.get_address(request.user, address_id)
        self.check_object_permissions(request, address)
        branch = domain.resolve_branch(
            request.user, _parse_uuid(request.query_params["branch_id"])
        )
        result = domain.resolve_branch_for_address(
            user=request.user,
            address_id=address_id,
            branch=branch,
        )
        payload = result.to_dict()
        return Response({
            "id": result.branch_id,
            "name": payload["name"],
            "status": payload["status"],
            "distance": payload["distance"],
            "delivery_radius": payload["delivery_radius"],
            "estimated_delivery_time": payload["estimated_delivery_time"],
        })


class AddressSuggestionsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AddressReadThrottle]

    @extend_schema(
        tags=["Users - Addresses"],
        summary="Address autocomplete suggestions",
        parameters=[
            OpenApiParameter("query", str, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("country", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("city", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("language", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: AddressSuggestionsResponseSerializer},
    )
    def get(self, request):
        suggestions = AddressDomainService().suggest_addresses(
            query=request.query_params.get("query", ""),
            country=request.query_params.get("country", ""),
            city=request.query_params.get("city", ""),
            language=request.query_params.get("language", ""),
        )
        return Response({"suggestions": suggestions})
