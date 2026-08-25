from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.api.serializers.response.rbac import (
    PermissionCatalogSerializer,
    TenantRoleListSerializer,
)
from access.services.rbac_bll import rbac_bll
from access.services.rbac_session_bll import rbac_session_bll


@extend_schema(
    tags=["Access - Permission"],
    summary="Permission catalog",
    description="Returns the static RBAC permission catalog for authenticated users.",
)
class PermissionCatalogListView(ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = PermissionCatalogSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        catalog = rbac_bll.get_permissions_catalog()
        serializer = self.get_serializer(catalog, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Access - Role"],
    summary="List tenant roles",
    description="Returns system roles and their permission grants.",
)
class TenantRoleListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, tenant_id):
        roles = rbac_session_bll.build_roles(tenant_id=tenant_id, user=request.user)
        serializer = TenantRoleListSerializer(roles, many=True)
        return Response(serializer.data)
