from uuid import UUID

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from addresses.api.permissions import IsAddressOwnerOrReadOnlyStaff
from addresses.api.serializers.request.address import (
    AddressUpdateSerializer,
    AddressWriteSerializer,
)
from addresses.api.serializers.response.address import AddressResponseSerializer
from addresses.api.throttling import (
    AddressCreateThrottle,
    AddressDeleteThrottle,
    AddressUpdateThrottle,
)
from addresses.services.address_domain_service import AddressDomainService


class AddressPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_uuid(value: str) -> UUID:
    return UUID(str(value))


def _optional_branch_id(request, domain: AddressDomainService):
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    return domain.resolve_branch(request.user, _parse_uuid(raw))


def _address_serializer_context(request, domain: AddressDomainService, address=None, branch=None):
    context = {"request": request, "domain_service": domain}
    if branch is not None:
        context["branch"] = branch
        if address is not None:
            context["capabilities"] = domain.get_capabilities(
                user=request.user, address=address, branch=branch
            )
    return context


@extend_schema_view(
    get=extend_schema(
        tags=["Users - Addresses"],
        summary="List user addresses",
        description="List addresses with full-text search, filtering, and pagination.",
        parameters=[
            OpenApiParameter("search", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("city", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("postal_code", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("title", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("ordering", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                "branch_id",
                str,
                OpenApiParameter.QUERY,
                required=False,
                description="When provided, includes per-address delivery capabilities.",
            ),
        ],
        responses={200: AddressResponseSerializer(many=True)},
    ),
    post=extend_schema(
        tags=["Users - Addresses"],
        summary="Create address",
        description=(
            "Create an address for the authenticated user. "
            "Identity fields (`first_name`, `last_name`, `country_code`, `phone`) and the "
            "address `title` (derived from `address_type`) are populated automatically from "
            "the user profile. Client-supplied identity values are ignored."
        ),
        request=AddressWriteSerializer,
        responses={201: AddressResponseSerializer},
        examples=[
            OpenApiExample(
                "Minimal create",
                value={
                    "address_type": "home",
                    "country": "US",
                    "province": "CA",
                    "city": "Los Angeles",
                    "street": "123 Main St",
                    "postal_code": "90001",
                    "latitude": 34.0522,
                    "longitude": -118.2437,
                    "is_default": True,
                },
                request_only=True,
            ),
        ],
    ),
)
class AddressListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = AddressPagination
    throttle_classes = [AddressCreateThrottle]

    def get_domain(self):
        return AddressDomainService()

    def get(self, request):
        domain = self.get_domain()
        branch = _optional_branch_id(request, domain)
        queryset = domain.list_addresses(
            request.user,
            search=request.query_params.get("search"),
            city=request.query_params.get("city"),
            postal_code=request.query_params.get("postal_code"),
            title=request.query_params.get("title"),
            ordering=request.query_params.get("ordering"),
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        results = [
            AddressResponseSerializer(
                item,
                context=_address_serializer_context(request, domain, item, branch),
            ).data
            for item in page
        ]
        return paginator.get_paginated_response(results)

    def post(self, request):
        serializer = AddressWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        domain = self.get_domain()
        branch = _optional_branch_id(request, domain)
        address = domain.create(
            request.user, serializer.validated_data, actor=request.user
        )
        return Response(
            AddressResponseSerializer(
                address,
                context=_address_serializer_context(request, domain, address, branch),
            ).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Users - Addresses"],
        summary="Retrieve address",
        parameters=[
            OpenApiParameter("branch_id", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: AddressResponseSerializer},
        examples=[
            OpenApiExample(
                "With capabilities",
                value={
                    "id": "00000000-0000-0000-0000-000000000001",
                    "capabilities": {
                        "can_deliver": True,
                        "supports_same_day": False,
                        "supports_scheduled_delivery": True,
                        "supports_cash_on_delivery": True,
                        "supports_contactless_delivery": True,
                    },
                },
                response_only=True,
            ),
        ],
    ),
    patch=extend_schema(
        tags=["Users - Addresses"],
        summary="Update address",
        description=(
            "Update address location and delivery details. "
            "Identity fields are refreshed from the authenticated user profile on every update."
        ),
        request=AddressUpdateSerializer,
        responses={200: AddressResponseSerializer},
    ),
    delete=extend_schema(tags=["Users - Addresses"], summary="Soft-delete address", responses={204: None}),
)
class AddressDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAddressOwnerOrReadOnlyStaff]
    throttle_classes = [AddressUpdateThrottle, AddressDeleteThrottle]

    def get_throttles(self):
        if self.request.method == "DELETE":
            return [AddressDeleteThrottle()]
        if self.request.method in ("PATCH", "PUT"):
            return [AddressUpdateThrottle()]
        return []

    def get_domain(self):
        return AddressDomainService()

    def get_object(self, request, address_id):
        address = self.get_domain().get_address(request.user, _parse_uuid(address_id))
        self.check_object_permissions(request, address)
        return address

    def get(self, request, address_id):
        address = self.get_object(request, address_id)
        domain = self.get_domain()
        branch = _optional_branch_id(request, domain)
        return Response(
            AddressResponseSerializer(
                address,
                context=_address_serializer_context(request, domain, address, branch),
            ).data
        )

    def patch(self, request, address_id):
        address = self.get_object(request, address_id)
        serializer = AddressUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        domain = self.get_domain()
        updated = domain.update(
            request.user, address.id, serializer.validated_data, actor=request.user
        )
        branch = _optional_branch_id(request, domain)
        return Response(
            AddressResponseSerializer(
                updated,
                context=_address_serializer_context(request, domain, updated, branch),
            ).data
        )

    def delete(self, request, address_id):
        address = self.get_object(request, address_id)
        self.get_domain().delete(request.user, address.id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Users - Addresses"],
    summary="Set default address",
    responses={200: AddressResponseSerializer},
)
class AddressSetDefaultView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AddressUpdateThrottle]

    def post(self, request, address_id):
        address = AddressDomainService().set_default(
            request.user, _parse_uuid(address_id), actor=request.user
        )
        return Response(AddressResponseSerializer(address).data)


@extend_schema(
    tags=["Users - Addresses"],
    summary="Restore soft-deleted address",
    responses={200: AddressResponseSerializer},
)
class AddressRestoreView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AddressUpdateThrottle]

    def post(self, request, address_id):
        address = AddressDomainService().restore(
            request.user, _parse_uuid(address_id), actor=request.user
        )
        return Response(AddressResponseSerializer(address).data)
