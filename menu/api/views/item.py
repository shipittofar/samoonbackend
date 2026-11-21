# menu/api/views/items.py
from decimal import Decimal, InvalidOperation

from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.generics import (
    CreateAPIView,
    UpdateAPIView,
    ListAPIView,
    RetrieveAPIView,
    DestroyAPIView
)
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from menu.api.serializers.request.menu import (
    TagFilterQuerySerializer,
    MenuItemSearchQuerySerializer,
)
from menu.utils.query_params import parse_tag_ids

from menu.api.serializers.request import (
    MenuItemInputSerializer,
    MenuItemUpdateSerializer,
    MenuItemBulkCreateInputSerializer,
    ExtraInputSerializer,
    ExtraUpdateSerializer,
    MenuItemExtraInputSerializer,
    MenuItemExtraUpdateSerializer,
    MenuItemAssignExtraGroupsSerializer,
)
from menu.services.item_bll import (
    ItemBusinessLogicLayer,
    ExtraBusinessLogicLayer,
    MenuItemExtraBusinessLogicLayer,
    MenuItemExtraGroupBusinessLogicLayer,
)
from menu.services.menu_bll import MenuBusinessLogicLayer
from menu.authorization.branch_menu import (
    PublicReadBranchMenuWriteMixin,
    RequireBranchMenuManagePermission,
    RequireBranchMenuViewPermission,
)
from menu.api.views.tenant_summary import (
    MenuPublicTenantSummaryMixin,
    tenant_summary_for_branch,
    wrap_public_menu_results,
)

from menu.api.serializers.response import (
    ExtraOutputSerializer,
    MenuItemExtraOutputSerializer,
    MenuItemOutputSerializer
)
from menu.models import MenuItem
from menu.selectors.item_dal import MenuItemExtraDataAccessLayer
from core.exceptions import MenuItemNotFoundException


extra_bll = ExtraBusinessLogicLayer()
item_extra_bll = MenuItemExtraBusinessLogicLayer()
item_extra_group_bll = MenuItemExtraGroupBusinessLogicLayer()
item_bll = ItemBusinessLogicLayer()
menu_bll = MenuBusinessLogicLayer()


def _menu_item_queryset():
    return MenuItem.objects.prefetch_related(
        "tags",
        "item_extras__extra",
        "item_extra_groups",
        "category",
    )


def _reload_menu_item_for_response(item):
    return (
        _menu_item_queryset()
        .filter(id=item.id)
        .first()
    ) or item


def _serialize_menu_item(item):
    return MenuItemOutputSerializer(item).data


def _serialize_menu_items(items):
    return MenuItemOutputSerializer(items, many=True).data


def _parse_bool_query(value):
    if value is None or value == "":
        return None
    normalized = str(value).lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _tags_from_request(request):
    return parse_tag_ids(request.query_params.get("tags"))


def _request_uses_item_filters(request) -> bool:
    """True when the client sent an explicit browse filter (not default listing)."""
    params = request.query_params
    if params.get("category") or params.get("search") or params.get("sort"):
        return True
    if params.get("tags"):
        return True
    if _parse_decimal_query(params.get("min_price")) is not None:
        return True
    if _parse_decimal_query(params.get("max_price")) is not None:
        return True
    if _parse_decimal_query(params.get("min_rating")) is not None:
        return True
    if _parse_bool_query(params.get("available")) is not None:
        return True
    return False


def _parse_decimal_query(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return None


def _get_filtered_items(request, branch_id):
    params = request.query_params
    return menu_bll.filter_items(
        branch_id,
        category=params.get("category"),
        search=params.get("search"),
        min_price=_parse_decimal_query(params.get("min_price")),
        max_price=_parse_decimal_query(params.get("max_price")),
        min_rating=_parse_decimal_query(params.get("min_rating")),
        available=_parse_bool_query(params.get("available")),
        sort=params.get("sort"),
        tags=_tags_from_request(request),
    )


def _resolve_branch_id(request, kwargs):
    """Support path-based branch_id and query-param alias routes."""
    return kwargs.get("branch_id") or request.query_params.get("branch_id")


def _perform_menu_item_partial_update(request, *, item_id, category_id, branch_id):
    """Shared partial-update flow for path-based and alias menu item routes."""
    input_serializer = MenuItemUpdateSerializer(
        data=request.data,
        partial=True,
    )
    input_serializer.is_valid(raise_exception=True)

    item = ItemBusinessLogicLayer.update_menu_item(
        item_id=item_id,
        category_id=category_id,
        branch_id=branch_id,
        **input_serializer.validated_data,
        image_provided="image" in request.data,
        image_asset_id_provided="image_asset_id" in request.data,
        tag_ids_provided="tag_ids" in request.data,
        extra_group_ids_provided="extra_group_ids" in request.data,
        user=request.user,
    )

    return Response(
        _serialize_menu_item(_reload_menu_item_for_response(item)),
        status=status.HTTP_200_OK,
    )


class ItemPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ExtraPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(tags=["Menu - Items"], summary="create Menu Items",
               request={
    "multipart/form-data": MenuItemInputSerializer,
},
)
class MenuItemCreateView(CreateAPIView):
    serializer_class = MenuItemInputSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        item = item_bll.create_menu_item(
            user=request.user,
            **input_serializer.validated_data
        )

        return Response(
            _serialize_menu_item(_reload_menu_item_for_response(item)),
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Menu - Items"], summary="create Menu Items",
               request={
    "multipart/form-data": MenuItemInputSerializer,
},
)
class ConsoleMenuItemCreateView(CreateAPIView):
    serializer_class = MenuItemInputSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        item = item_bll.create_menu_item(
            user=request.user,
            **input_serializer.validated_data
        )

        return Response(
            _serialize_menu_item(_reload_menu_item_for_response(item)),
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Menu - Items"], summary="Bulk create Menu Items")
class MenuItemBulkCreateView(CreateAPIView):
    serializer_class = MenuItemBulkCreateInputSerializer
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        items = item_bll.bulk_create_menu_items(
            input_serializer.validated_data["items"]
        )
        item_ids = [item.id for item in items]
        items = list(_menu_item_queryset().filter(id__in=item_ids))

        output_serializer = MenuItemOutputSerializer(items, many=True)
        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Menu - Items"], summary="list Menu Items for Console")
class ConsoleMenuItemListView(ListAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuViewPermission]
    serializer_class = MenuItemOutputSerializer
    pagination_class = ItemPagination

    def get_queryset(self):
        return ItemBusinessLogicLayer.get_item_list_for_console(
            branch_id=self.kwargs["branch_id"],
        )


@extend_schema(tags=["Menu - Items"], summary="update partial Menu Items",
               request={
    "multipart/form-data": MenuItemUpdateSerializer,
},
)
class MenuItemUpdateView(UpdateAPIView):
    serializer_class = MenuItemUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    http_method_names = ["patch", "put"]

    def partial_update(self, request, *args, **kwargs):
        return _perform_menu_item_partial_update(
            request,
            item_id=kwargs["pk"],
            category_id=kwargs["category_id"],
            branch_id=kwargs["branch_id"],
        )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


@extend_schema(
    tags=["Menu - Items"],
    summary="list Menu Items",
    parameters=[TagFilterQuerySerializer],
)
class MenuItemListView(MenuPublicTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = ItemPagination

    def get_queryset(self):
        return ItemBusinessLogicLayer.get_item_list(
            branch_id=self.kwargs["branch_id"],
            category_id=self.kwargs["category_id"],
            tags=_tags_from_request(self.request),
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="list Menu Items (frontend alias)",
    description=(
        "Returns all active menu items for the specified branch via "
        "/items/?branch_id={id} or /items/branches/{branch_id}/."
    ),
    parameters=[TagFilterQuerySerializer],
)
class MenuItemAliasListView(MenuPublicTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = ItemPagination

    def get_queryset(self):
        branch_id = _resolve_branch_id(self.request, self.kwargs)
        if _request_uses_item_filters(self.request):
            return _get_filtered_items(self.request, branch_id)
        return menu_bll.get_active_items(
            branch_id=branch_id,
            tags=_tags_from_request(self.request),
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="Menu item collection (frontend alias)",
    description="GET list or POST create via /items/?branch_id=X.",
)
class MenuItemCollectionAliasView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsAuthenticated(), RequireBranchMenuManagePermission()]

    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        if _request_uses_item_filters(request):
            items = _get_filtered_items(request, branch_id)
        else:
            items = menu_bll.get_active_items(
                branch_id=branch_id,
                tags=_tags_from_request(request),
            )
        paginator = ItemPagination()
        page = paginator.paginate_queryset(items, request, view=self)
        if page is not None:
            response = paginator.get_paginated_response(_serialize_menu_items(page))
            response.data.update(tenant_summary_for_branch(branch_id))
            return response
        return Response(
            wrap_public_menu_results(branch_id, _serialize_menu_items(items)),
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        input_serializer = MenuItemInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        item = item_bll.create_menu_item(**input_serializer.validated_data, user=request.user)
        return Response(
            _serialize_menu_item(_reload_menu_item_for_response(item)),
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="Featured menu items (frontend alias)",
    parameters=[TagFilterQuerySerializer],
)
class MenuItemFeaturedAliasView(APIView):
    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        items = menu_bll.get_featured_items(
            branch_id=branch_id,
            tags=_tags_from_request(request),
        )
        return Response(
            wrap_public_menu_results(branch_id, _serialize_menu_items(items)),
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="Popular menu items (frontend alias)",
    parameters=[TagFilterQuerySerializer],
)
class MenuItemPopularAliasView(APIView):
    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        items = menu_bll.get_popular_items(
            branch_id=branch_id,
            tags=_tags_from_request(request),
        )
        return Response(
            wrap_public_menu_results(branch_id, _serialize_menu_items(items)),
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="Search menu items (frontend alias)",
    parameters=[MenuItemSearchQuerySerializer],
)
class MenuItemSearchAliasView(APIView):
    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        query = request.query_params.get("q", "")
        items = menu_bll.search_items(
            branch_id=branch_id,
            query=query,
            tags=_tags_from_request(request),
        )
        return Response(
            wrap_public_menu_results(branch_id, _serialize_menu_items(items)),
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="Related menu items (frontend alias)",
    parameters=[TagFilterQuerySerializer],
)
class MenuItemRelatedAliasView(APIView):
    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        items = menu_bll.get_related_items(
            branch_id=branch_id,
            item_id=kwargs["pk"],
            tags=_tags_from_request(request),
        )
        return Response(
            wrap_public_menu_results(branch_id, _serialize_menu_items(items)),
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Items"],
    summary="update Menu Item (frontend alias)",
    description=(
        "Partially update a menu item via PATCH or POST on "
        "/items/{id}/?branch_id={id}."
    ),
    request={"multipart/form-data": MenuItemUpdateSerializer},
)
class MenuItemDetailAliasView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsAuthenticated(), RequireBranchMenuManagePermission()]

    def _get_item(self, request, kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        item = (
            _menu_item_queryset()
            .filter(id=kwargs["pk"], branch_id=branch_id)
            .first()
        )
        if item is None:
            raise MenuItemNotFoundException()
        return item, branch_id

    def get(self, request, *args, **kwargs):
        item, branch_id = self._get_item(request, kwargs)
        if not item.is_active:
            raise MenuItemNotFoundException()
        payload = _serialize_menu_item(item)
        payload.update(tenant_summary_for_branch(branch_id))
        return Response(payload, status=status.HTTP_200_OK)

    def _partial_update(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        item_id = kwargs["pk"]

        existing = MenuItemExtraDataAccessLayer.get_item_by_id_and_branch(
            item_id, branch_id
        )
        if existing is None:
            raise MenuItemNotFoundException()

        return _perform_menu_item_partial_update(
            request,
            item_id=item_id,
            category_id=existing.category_id,
            branch_id=branch_id,
        )

    def patch(self, request, *args, **kwargs):
        return self._partial_update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self._partial_update(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self._partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        item, branch_id = self._get_item(request, kwargs)
        ItemBusinessLogicLayer.delete_menu_item(
            item_id=item.id,
            category_id=item.category_id,
            branch_id=branch_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Menu - Items"], summary="detail Menu Items")
class MenuItemDetailView(RetrieveAPIView):
    serializer_class = MenuItemOutputSerializer

    def retrieve(self, request, *args, **kwargs):
        branch_id = kwargs["branch_id"]
        item = ItemBusinessLogicLayer.get_item_detail(
            item_id=kwargs["pk"],
            category_id=kwargs["category_id"],
            branch_id=branch_id,
        )
        payload = _serialize_menu_item(_reload_menu_item_for_response(item))
        payload.update(tenant_summary_for_branch(branch_id))
        return Response(payload, status=status.HTTP_200_OK)


@extend_schema(tags=["Menu - Items"], summary="Soft-delete menu item (sets deleted_at)")
class MenuItemDeleteView(DestroyAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def destroy(self, request, *args, **kwargs):
        ItemBusinessLogicLayer.delete_menu_item(
            item_id=kwargs["pk"],
            category_id=kwargs["category_id"],
            branch_id=kwargs["branch_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Menu - Extras"],
    summary="create Extra",
    description="Create a new extra for the specified branch."
)
class ExtraCreateView(CreateAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    serializer_class = ExtraInputSerializer

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        extra = extra_bll.create_extra(**input_serializer.validated_data)

        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Extras"],
    summary="list Extras",
    description="Retrieve a paginated list of extras for the specified branch."
)
class ExtraListView(ListAPIView):
    serializer_class = ExtraOutputSerializer
    pagination_class = ExtraPagination

    def get_queryset(self):
        branch_id = self.kwargs.get("branch_id") or self.request.query_params.get(
            "branch_id"
        )
        group_id = self.request.query_params.get("group_id")
        return extra_bll.get_extra_list(branch_id=branch_id, group_id=group_id)


@extend_schema(
    tags=["Menu - Extras"],
    summary="detail Extra",
    description="Retrieve the details of a specific extra."
)
class ExtraDetailView(RetrieveAPIView):
    serializer_class = ExtraOutputSerializer

    def retrieve(self, request, *args, **kwargs):
        branch_id = kwargs.get(
            "branch_id") or request.query_params.get("branch_id")
        extra = extra_bll.get_extra_detail(
            extra_id=kwargs["pk"],
            branch_id=branch_id,
        )
        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Extras"],
    summary="update partial Extra",
    description="Partially update an existing extra."
)
class ExtraUpdateView(UpdateAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    serializer_class = ExtraUpdateSerializer
    http_method_names = ["patch"]

    def partial_update(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        validated = input_serializer.validated_data
        extra = extra_bll.update_extra(
            extra_id=kwargs["pk"],
            branch_id=kwargs.get(
                "branch_id") or request.query_params.get("branch_id"),
            **validated,
            group_id_provided="group_id" in request.data,
        )

        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Extras"],
    summary="Delete extra, or deactivate if referenced by orders",
    description=(
        "Hard-deletes an extra only when unused by historical order snapshots. "
        "If OrderItemExtra references exist, the extra is marked unavailable and a 409 is returned."
    )
)
class ExtraDeleteView(DestroyAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def destroy(self, request, *args, **kwargs):
        branch_id = kwargs.get(
            "branch_id") or request.query_params.get("branch_id")
        extra_bll.delete_extra(
            extra_id=kwargs["pk"],
            branch_id=branch_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Menu - Extras"],
    summary="Extra collection (frontend alias)",
    description="GET list or POST create via /extras/.",
)
class ExtraCollectionAliasView(PublicReadBranchMenuWriteMixin, APIView):
    def get(self, request, *args, **kwargs):
        branch_id = request.query_params.get("branch_id")
        group_id = request.query_params.get("group_id")
        extras = extra_bll.get_extra_list(
            branch_id=branch_id, group_id=group_id)
        return Response(
            ExtraOutputSerializer(extras, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        input_serializer = ExtraInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        extra = extra_bll.create_extra(**input_serializer.validated_data)
        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Extras"],
    summary="Extra detail (frontend alias)",
    description="GET, PATCH, or DELETE via /extras/{id}/.",
)
class ExtraDetailAliasView(PublicReadBranchMenuWriteMixin, APIView):
    def get(self, request, *args, **kwargs):
        branch_id = request.query_params.get("branch_id")
        extra = extra_bll.get_extra_detail(
            extra_id=kwargs["pk"], branch_id=branch_id
        )
        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, *args, **kwargs):
        input_serializer = ExtraUpdateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        extra = extra_bll.update_extra(
            extra_id=kwargs["pk"],
            branch_id=request.query_params.get("branch_id"),
            **input_serializer.validated_data,
            group_id_provided="group_id" in request.data,
        )
        return Response(
            ExtraOutputSerializer(extra).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, *args, **kwargs):
        extra_bll.delete_extra(
            extra_id=kwargs["pk"],
            branch_id=request.query_params.get("branch_id"),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Menu - Items"],
    summary="assign Extra Groups to Item",
    description=(
        "Attach or detach extra groups on a menu item and materialize "
        "MenuItemExtra links for order compatibility."
    ),
)
class MenuItemAssignExtraGroupsView(UpdateAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    serializer_class = MenuItemAssignExtraGroupsSerializer
    http_method_names = ["patch"]

    def patch(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        branch_id = kwargs.get(
            "branch_id") or request.query_params.get("branch_id")
        item_id = kwargs.get("item_id") or kwargs.get("pk")

        item = item_extra_group_bll.assign_extra_groups_to_item(
            item_id=item_id,
            branch_id=branch_id,
            group_ids=input_serializer.validated_data["extra_group_ids"],
        )

        return Response(
            _serialize_menu_item(_reload_menu_item_for_response(item)),
            status=status.HTTP_200_OK,
        )


# ---- MenuItem <-> Extra links ----

@extend_schema(
    tags=["Menu - Item Extras"],
    summary="attach Extra to Item",
    description="Attach an existing extra to a menu item."
)
class MenuItemExtraCreateView(CreateAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    serializer_class = MenuItemExtraInputSerializer

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        link = item_extra_bll.create_item_extra(
            item_id=kwargs["item_id"],
            branch_id=kwargs["branch_id"],
            **input_serializer.validated_data,
        )

        return Response(
            MenuItemExtraOutputSerializer(link).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Item Extras"],
    summary="list Item's Extras",
    description="Retrieve all extras assigned to a specific menu item."
)
class MenuItemExtraListView(ListAPIView):
    serializer_class = MenuItemExtraOutputSerializer

    def get_queryset(self):
        return item_extra_bll.get_item_extra_list(
            item_id=self.kwargs["item_id"],
            branch_id=self.kwargs["branch_id"],
        )


@extend_schema(
    tags=["Menu - Item Extras"],
    summary="update Item Extra price override",
    description="Update the price override or settings for an extra assigned to a menu item."
)
class MenuItemExtraUpdateView(UpdateAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    serializer_class = MenuItemExtraUpdateSerializer
    http_method_names = ["patch"]

    def partial_update(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        link = item_extra_bll.update_item_extra(
            item_id=kwargs["item_id"],
            branch_id=kwargs["branch_id"],
            extra_id=kwargs["extra_id"],
            **input_serializer.validated_data,
            price_override_provided="price_override" in request.data,
        )

        return Response(
            MenuItemExtraOutputSerializer(link).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Item Extras"],
    summary="detach Extra from Item",
    description="Remove an extra from a menu item."
)
class MenuItemExtraDeleteView(DestroyAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def destroy(self, request, *args, **kwargs):
        item_extra_bll.delete_item_extra(
            item_id=kwargs["item_id"],
            branch_id=kwargs["branch_id"],
            extra_id=kwargs["extra_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
