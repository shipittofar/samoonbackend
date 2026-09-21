from rest_framework.generics import (
    CreateAPIView,
    UpdateAPIView,
    RetrieveAPIView,
    ListAPIView,
    DestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view

from tenants.api.serializers.response import *
from tenants.api.serializers.request import *
from tenants.services import TenantBusinessLogicLayer, BranchBusinessLogicLayer


tenant_bll = TenantBusinessLogicLayer()
branch_bll = BranchBusinessLogicLayer()


class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

# ---------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------


@extend_schema(tags=["Tenant - Tenant"], summary="create Tenant")
class TenantCreateAPIView(CreateAPIView):
    serializer_class = TenantCreateSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = (IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = tenant_bll.create_tenant(
            user=request.user, **serializer.validated_data)

        return Response(
            TenantResponseSerializer(tenant, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    put=extend_schema(tags=["Tenant - Tenant"], summary="update Tenant"),
    patch=extend_schema(tags=["Tenant - Tenant"],
                        summary="partial update Tenant"),
)
class TenantUpdateAPIView(UpdateAPIView):
    serializer_class = TenantUpdateSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = (IsAuthenticated,)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = tenant_bll.update_tenant(
            user=request.user,
            tenant_id=kwargs["tenant_id"],
            **serializer.validated_data,
        )

        return Response(TenantResponseSerializer(tenant, context={"request": request}).data)


@extend_schema(tags=["Tenant - Tenant"], summary="patch Tenant settings")
class TenantSettingsPatchAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, tenant_id, *args, **kwargs):
        tenant = tenant_bll.patch_tenant_settings(
            user=request.user,
            tenant_id=tenant_id,
            patch=dict(request.data),
        )
        return Response(TenantResponseSerializer(tenant, context={"request": request}).data)


@extend_schema(tags=["Tenant - Tenant"], summary="retrieve Tenant (public catalog)")
class TenantRetrieveAPIView(RetrieveAPIView):
    """Public tenant detail — hidden/non-listable tenants return 404."""

    def retrieve(self, request, *args, **kwargs):
        tenant = tenant_bll.get_public_tenant(tenant_id=kwargs["tenant_id"])
        return Response(
            TenantResponseSerializer(
                tenant,
                context={"public_settings": True, "request": request},
            ).data
        )


@extend_schema(tags=["Tenant - Tenant"], summary="list public tenants (discover)")
class TenantListAPIView(ListAPIView):
    serializer_class = PublicTenantResponseSerializer
    pagination_class = DefaultPagination
    permission_classes = ()
    authentication_classes = ()

    def get_queryset(self):
        return tenant_bll.get_public_tenants()


@extend_schema(tags=["Tenant - Tenant"], summary="list Tenants for console")
class ConsoleTenantListAPIView(ListAPIView):
    serializer_class = TenantResponseSerializer
    pagination_class = DefaultPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return tenant_bll.get_console_tenants(user=self.request.user)


@extend_schema(tags=["Tenant - Tenant"], summary="Deactivate tenant")
class TenantDeleteView(DestroyAPIView):
    permission_classes = (IsAuthenticated,)

    def destroy(self, request, *args, **kwargs):
        tenant_bll.delete_tenant(
            user=request.user, tenant_id=kwargs["tenant_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Tenant - Tenant"], summary="list Tenants owned by the current user")
class TenantMeListAPIView(ListAPIView):
    serializer_class = TenantResponseSerializer
    pagination_class = DefaultPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return tenant_bll.get_my_tenants(user=self.request.user)

# ---------------------------------------------------------------------
# Branch (nested under Tenant)
# ---------------------------------------------------------------------


@extend_schema(tags=["Tenant - Branch"], summary="create Branch")
class BranchCreateAPIView(CreateAPIView):
    serializer_class = BranchConsoleCreateSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    permission_classes = (IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        branch = branch_bll.create_branch(
            user=request.user,
            tenant_id=kwargs["tenant_id"],
            **serializer.validated_data,
        )

        return Response(
            BranchResponseSerializer(branch, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    put=extend_schema(tags=["Tenant - Branch"], summary="update Branch"),
    patch=extend_schema(tags=["Tenant - Branch"],
                        summary="partial update Branch"),
)
class BranchUpdateAPIView(UpdateAPIView):
    serializer_class = BranchUpdateSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    permission_classes = (IsAuthenticated,)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        branch = branch_bll.update_branch(
            user=request.user,
            tenant_id=kwargs["tenant_id"],
            branch_id=kwargs["branch_id"],
            **serializer.validated_data,
        )

        return Response(BranchResponseSerializer(branch, context={"request": request}).data)


@extend_schema(tags=["Tenant - Branch"], summary="retrieve Branch")
class BranchRetrieveAPIView(RetrieveAPIView):
    """Tenant-scoped branch deep-link.

    Intentionally AllowAny: storefront flows that already hold ``tenant_id`` may
    load branch details even when the tenant is hidden from public catalogs.
    Tenant visibility/usability is returned via the nested ``tenant`` object.
    """

    def retrieve(self, request, *args, **kwargs):
        branch = branch_bll.get_branch(
            tenant_id=kwargs["tenant_id"],
            branch_id=kwargs["branch_id"],
        )
        return Response(BranchResponseSerializer(branch, context={"request": request}).data)


@extend_schema(tags=["Tenant - Branch"], summary="list Branches for a Tenant")
class BranchListAPIView(ListAPIView):
    """Tenant-scoped branch list (deep-link / storefront).

    Not filtered by public catalog rules — see ``BranchRetrieveAPIView``.
    """
    serializer_class = BranchResponseSerializer
    pagination_class = DefaultPagination

    def get_queryset(self):
        return branch_bll.get_branches(tenant_id=self.kwargs["tenant_id"])


@extend_schema(tags=["Tenant - Branch"], summary="Deactivate branch")
class BranchDeleteView(DestroyAPIView):
    permission_classes = (IsAuthenticated,)

    def destroy(self, request, *args, **kwargs):
        branch_bll.delete_branch(
            user=request.user,
            tenant_id=kwargs["tenant_id"],
            branch_id=kwargs["branch_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Tenant - Branch"], summary="Deactivate branch")
class ConsoleBranchDeleteView(DestroyAPIView):
    permission_classes = (IsAuthenticated,)

    def destroy(self, request, *args, **kwargs):
        branch_bll.delete_console_branch(
            user=request.user,
            branch_id=kwargs["branch_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    patch=extend_schema(tags=["Branches - Console"], summary="update Branch"),
)
class BranchConsoleUpdateAPIView(APIView):
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    permission_classes = (IsAuthenticated,)

    def patch(self, request, branch_id, *args, **kwargs):
        serializer = BranchConsoleUpdateSerializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        branch = branch_bll.update_console_branch(
            user=request.user,
            branch_id=branch_id,
            image_provided="image" in request.data,
            cover_image_provided=(
                "coverImage" in request.data or "cover_image" in request.data
            ),
            hero_image_provided=(
                "heroImage" in request.data or "hero_image" in request.data
            ),
            **serializer.validated_data,
        )

        return Response(
            BranchResponseSerializer(branch, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------
# Branch (global / public — not nested under Tenant)
# ---------------------------------------------------------------------


@extend_schema(tags=["Tenant - Branch"], summary="list all Branches (public)")
class BranchGlobalListAPIView(ListAPIView):
    serializer_class = BranchResponseSerializer
    pagination_class = DefaultPagination

    def get_queryset(self):
        return branch_bll.get_all_branches()


@extend_schema(tags=["Tenant - Branch"], summary="retrieve Branch (public)")
class BranchGlobalRetrieveAPIView(RetrieveAPIView):

    def retrieve(self, request, *args, **kwargs):
        branch = branch_bll.get_branch_public(branch_id=kwargs["branch_id"])
        return Response(BranchResponseSerializer(branch, context={"request": request}).data)
