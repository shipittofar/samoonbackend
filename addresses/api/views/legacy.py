"""Backward-compatible /api/orders/addresses/ endpoints."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from addresses.api.serializers.request.address import LegacyAddressWriteSerializer
from addresses.api.serializers.response.address import LegacyAddressResponseSerializer
from addresses.api.views.address import AddressPagination
from addresses.services.address_domain_service import AddressDomainService


@extend_schema_view(
    get=extend_schema(
        tags=["Orders - Address"],
        summary="List addresses (legacy)",
        responses={200: LegacyAddressResponseSerializer(many=True)},
    ),
    post=extend_schema(
        tags=["Orders - Address"],
        summary="Create address (legacy)",
        request=LegacyAddressWriteSerializer,
        responses={201: LegacyAddressResponseSerializer},
    ),
)
class LegacyAddressListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = AddressPagination

    def get(self, request):
        queryset = AddressDomainService().list_addresses(request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = LegacyAddressResponseSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = LegacyAddressWriteSerializer(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        address = AddressDomainService().create(
            request.user, serializer.validated_data, actor=request.user
        )
        return Response(
            LegacyAddressResponseSerializer(address).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(tags=["Orders - Address"], summary="Retrieve address (legacy)", responses={200: LegacyAddressResponseSerializer}),
    patch=extend_schema(tags=["Orders - Address"], summary="Update address (legacy)", responses={200: LegacyAddressResponseSerializer}),
    delete=extend_schema(tags=["Orders - Address"], summary="Delete address (legacy)", responses={204: None}),
)
class LegacyAddressDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, address_id: int):
        return AddressDomainService().get_address(request.user, address_id)

    def get(self, request, address_id: int):
        address = self.get_object(request, address_id)
        return Response(LegacyAddressResponseSerializer(address).data)

    def patch(self, request, address_id: int):
        address = self.get_object(request, address_id)
        mapping = {
            "label": "address_type",
            "street": "street",
            "city": "city",
            "state": "province",
            "zip": "postal_code",
            "lat": "latitude",
            "lng": "longitude",
            "is_default": "is_default",
        }
        validated = {}
        for legacy_key, model_key in mapping.items():
            if legacy_key in request.data:
                validated[model_key] = request.data[legacy_key]
        if not validated:
            return Response(LegacyAddressResponseSerializer(address).data)
        updated = AddressDomainService().update(
            request.user, address.id, validated, actor=request.user
        )
        return Response(LegacyAddressResponseSerializer(updated).data)

    def delete(self, request, address_id: int):
        address = self.get_object(request, address_id)
        AddressDomainService().delete(request.user, address.id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
