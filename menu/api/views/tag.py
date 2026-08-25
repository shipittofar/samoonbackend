from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from menu.api.serializers.request.tag import (
    AvailableTagQuerySerializer,
    TagInputSerializer,
    TagUpdateSerializer,
)
from menu.api.serializers.response.tag import (
    AvailableTagOutputSerializer,
    TagManagementOutputSerializer,
)
from menu.authorization.branch_menu import RequireBranchMenuManagePermission
from menu.services.tag_bll import TagBusinessLogicLayer


tag_bll = TagBusinessLogicLayer()


class TagPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_bool_query(value):
    if value is None or value == "":
        return None
    normalized = str(value).lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


@extend_schema(
    tags=["Menu - Tags"],
    summary="List or create branch tags",
    description="GET: paginated tags. POST: create a tag. Supports search, ordering, and active filter.",
    parameters=[
        OpenApiParameter(name="search", type=str, description="Search name, slug, or description"),
        OpenApiParameter(name="is_active", type=bool, description="Filter by active status"),
        OpenApiParameter(
            name="ordering",
            type=str,
            description="display_order, -display_order, name, -name, created_at, -created_at",
        ),
    ],
)
class BranchTagListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        queryset = tag_bll.get_tag_list(
            branch_id=kwargs["branch_id"],
            search=params.get("search") or None,
            is_active=_parse_bool_query(params.get("is_active")),
            ordering=params.get("ordering") or None,
        )
        paginator = TagPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = TagManagementOutputSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, *args, **kwargs):
        input_serializer = TagInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        tag = tag_bll.create_tag(
            branch_id=kwargs["branch_id"],
            **input_serializer.validated_data,
        )

        return Response(
            TagManagementOutputSerializer(tag).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Tags"],
    summary="Retrieve, update, or delete branch tag",
    request={"multipart/form-data": TagUpdateSerializer},
)
class BranchTagDetailView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def get(self, request, *args, **kwargs):
        tag = tag_bll.get_tag_detail(
            tag_id=kwargs["id"],
            branch_id=kwargs["branch_id"],
        )
        return Response(
            TagManagementOutputSerializer(tag).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, *args, **kwargs):
        input_serializer = TagUpdateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        tag = tag_bll.update_tag(
            tag_id=kwargs["id"],
            branch_id=kwargs["branch_id"],
            **input_serializer.validated_data,
            image_provided="image" in request.data,
        )

        return Response(
            TagManagementOutputSerializer(tag).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, *args, **kwargs):
        tag_bll.delete_tag(
            tag_id=kwargs["id"],
            branch_id=kwargs["branch_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Menu - Tags"],
    summary="List available storefront tags",
    description="Public endpoint returning active tags for storefront filters.",
    parameters=[AvailableTagQuerySerializer],
)
class AvailableTagListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        query = AvailableTagQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        include_item_count = query.validated_data["include_item_count"]

        tags = tag_bll.get_available_tags(
            branch_id=kwargs["branch_id"],
            include_item_count=include_item_count,
        )

        serializer = AvailableTagOutputSerializer(
            tags,
            many=True,
            context={"include_item_count": include_item_count},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
