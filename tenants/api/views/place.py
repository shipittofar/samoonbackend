from rest_framework.generics import (
    CreateAPIView,
    UpdateAPIView,
    RetrieveAPIView,
    ListAPIView,
    DestroyAPIView,
)
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, extend_schema_view

from tenants.api.serializers.response import *
from tenants.api.serializers.request import *
from tenants.services import TenantBusinessLogicLayer


tenant_bll = TenantBusinessLogicLayer()


class TenantPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(tags=["Tenant - Tenant"], summary="create Tenants")
class TenantCreateAPIView(CreateAPIView):
    serializer_class = TenantCreateSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = tenant_bll.create_tenant(**serializer.validated_data)

        return Response(
            TenantCreateResponseSerializer(tenant).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    put=extend_schema(tags=["Tenant - Tenant"], summary="update Tenants"),
    patch=extend_schema(tags=["Tenant - Tenant"], summary="partial update Tenants"),
)
class TenantUpdateAPIView(UpdateAPIView):
    serializer_class = TenantUpdateSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = tenant_bll.update_tenant(
            tenant_id=kwargs["tenant_id"],
            actor_id=request.user.id,
            **serializer.validated_data,
        )

        return Response(
            TenantRetrieveResponseSerializer(tenant).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Tenant - Tenant"], summary="retrieve Tenants")
class TenantRetrieveAPIView(RetrieveAPIView):

    def retrieve(self, request, *args, **kwargs):
        tenant = tenant_bll.get_tenant(tenant_id=kwargs["tenant_id"])

        return Response(TenantRetrieveResponseSerializer(tenant).data)


@extend_schema(tags=["Tenant - Tenant"], summary="list Tenants")
class TenantListAPIView(ListAPIView):
    serializer_class = TenantRetrieveResponseSerializer
    pagination_class = TenantPagination

    def get_queryset(self):
        return tenant_bll.get_tenants()


@extend_schema(tags=["Tenant - Tenant"], summary="Deactivate tenant")
class TenantDeleteView(DestroyAPIView):

    def destroy(self, request, *args, **kwargs):
        tenant_bll.delete_tenant(tenant_id=kwargs["tenant_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)