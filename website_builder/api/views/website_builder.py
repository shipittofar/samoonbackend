from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.authorization import RequirePermission
from website_builder.api.serializers import (
    BranchContentOverridesSerializer,
    HomepageLayoutSerializer,
    WebsiteMediaUploadResponseSerializer,
    WebsiteMediaUploadSerializer,
)
from website_builder.services import WebsiteBuilderBusinessLogicLayer

website_bll = WebsiteBuilderBusinessLogicLayer()


class WebsiteBuilderPermissionMixin:
    permission_classes = (IsAuthenticated, RequirePermission("settings.view"))


@extend_schema_view(
    get=extend_schema(
        tags=["Tenant - Website Builder"],
        summary="Get tenant website layout",
        responses={200: HomepageLayoutSerializer},
    ),
    put=extend_schema(
        tags=["Tenant - Website Builder"],
        summary="Save tenant website layout",
        request=HomepageLayoutSerializer,
        responses={200: HomepageLayoutSerializer},
    ),
)
class WebsiteLayoutAPIView(WebsiteBuilderPermissionMixin, APIView):
    parser_classes = (JSONParser,)

    def get_permissions(self):
        # initialize_request/get_permissions may run before request is bound
        # (e.g. drf-spectacular schema generation); only treat real GETs as public.
        if getattr(self.request, "method", None) == "GET":
            return [AllowAny()]
        return super().get_permissions()

    def get(self, request, tenant_id, *args, **kwargs):
        layout = website_bll.get_layout(tenant_id=tenant_id)
        return Response(HomepageLayoutSerializer(layout).data)

    def put(self, request, tenant_id, *args, **kwargs):
        serializer = HomepageLayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        layout = website_bll.save_layout(
            tenant_id=tenant_id,
            layout_data=serializer.validated_data,
        )
        return Response(HomepageLayoutSerializer(layout).data)


@extend_schema_view(
    get=extend_schema(
        tags=["Tenant - Website Builder"],
        summary="Get branch website content overrides",
        responses={200: BranchContentOverridesSerializer},
    ),
    put=extend_schema(
        tags=["Tenant - Website Builder"],
        summary="Save branch website content overrides",
        request=BranchContentOverridesSerializer,
        responses={200: BranchContentOverridesSerializer},
    ),
)
class BranchWebsiteOverridesAPIView(WebsiteBuilderPermissionMixin, APIView):
    parser_classes = (JSONParser,)

    def get(self, request, tenant_id, branch_id, *args, **kwargs):
        overrides = website_bll.get_branch_overrides(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )
        return Response(BranchContentOverridesSerializer(overrides).data)

    def put(self, request, tenant_id, branch_id, *args, **kwargs):
        serializer = BranchContentOverridesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        overrides = website_bll.save_branch_overrides(
            tenant_id=tenant_id,
            branch_id=branch_id,
            override_data=serializer.validated_data,
        )
        return Response(BranchContentOverridesSerializer(overrides).data)


@extend_schema(
    tags=["Tenant - Website Builder"],
    summary="Upload website media",
    request=WebsiteMediaUploadSerializer,
    responses={201: WebsiteMediaUploadResponseSerializer},
)
class WebsiteMediaUploadAPIView(WebsiteBuilderPermissionMixin, APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, tenant_id, *args, **kwargs):
        serializer = WebsiteMediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = website_bll.upload_media(
            tenant_id=tenant_id,
            uploaded_file=serializer.validated_data["file"],
        )
        if request and not str(url).startswith(("http://", "https://")):
            url = request.build_absolute_uri(url)
        return Response({"url": url}, status=status.HTTP_201_CREATED)
