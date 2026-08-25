from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView

from tenants.api.serializers.response.discover_response import (
    DiscoverTenantResponseSerializer,
)
from tenants.api.views.tenant import DefaultPagination
from tenants.services import TenantBusinessLogicLayer


tenant_bll = TenantBusinessLogicLayer()


@extend_schema(
    tags=["Public - Discover"],
    summary="list marketplace tenants with public branches",
)
class DiscoverListAPIView(ListAPIView):
    """GET /api/public/discover/ — paginated public marketplace directory.

    Returns active tenants, their public marketplace metadata, and
    marketplace-visible branches in a single response.
    """

    serializer_class = DiscoverTenantResponseSerializer
    pagination_class = DefaultPagination
    permission_classes = ()
    authentication_classes = ()

    def get_queryset(self):
        return tenant_bll.get_discover_tenants()
