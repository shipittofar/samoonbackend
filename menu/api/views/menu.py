from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema

from menu.api.serializers.request.menu import (
    ItemPriceQuerySerializer,
    ItemPreparationTimeQuerySerializer,
    ItemCalorieQuerySerializer,
    ItemDiscountQuerySerializer,
    TagFilterQuerySerializer,
)
from menu.api.serializers.response.menu import (
    MenuCategoryWithItemsOutputSerializer,
    MenuItemOutputSerializer,
)
from menu.services.menu_bll import MenuBusinessLogicLayer
from menu.api.views.tenant_summary import MenuPublicTenantSummaryMixin
from menu.utils.query_params import parse_tag_ids


menu_bll = MenuBusinessLogicLayer()


class MenuPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _tags_from_request(request):
    return parse_tag_ids(request.query_params.get("tags"))


# Backward-compatible alias for existing imports/tests.
MenuBrowseTenantSummaryMixin = MenuPublicTenantSummaryMixin


@extend_schema(
    tags=["Menu - Browse"],
    summary="List categories with their items",
    description="Returns all active menu categories with their active items for the specified branch.",
    parameters=[TagFilterQuerySerializer],
)
class CategoryWithItemsListView(ListAPIView):
    serializer_class = MenuCategoryWithItemsOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        return menu_bll.get_categories_with_items(
            branch_id=self.kwargs["branch_id"],
            tags=_tags_from_request(self.request),
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data.update(
            menu_bll.get_categories_with_items_summary(branch_id=self.kwargs["branch_id"])
        )
        return response


@extend_schema(
    tags=["Menu - Browse"],
    summary="List popular items",
    description="Returns the most popular menu items for the specified branch.",
    parameters=[TagFilterQuerySerializer],
)
class PopularItemListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        return menu_bll.get_popular_items(
            branch_id=self.kwargs["branch_id"],
            tags=_tags_from_request(self.request),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="List featured items",
    description="Returns featured menu items selected by the business.",
    parameters=[TagFilterQuerySerializer],
)
class FeaturedItemListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        return menu_bll.get_featured_items(
            branch_id=self.kwargs["branch_id"],
            tags=_tags_from_request(self.request),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="List active items",
    description="Returns all active menu items available in the specified branch.",
    parameters=[TagFilterQuerySerializer],
)
class ActiveItemListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        return menu_bll.get_active_items(
            branch_id=self.kwargs["branch_id"],
            tags=_tags_from_request(self.request),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="Filter items by price",
    description="Returns menu items filtered by price range or sorted by price.",
    parameters=[ItemPriceQuerySerializer],
)
class ItemByPriceListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        query = ItemPriceQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        return menu_bll.get_items_by_price(
            branch_id=self.kwargs["branch_id"],
            min_value=data.get("min_price"),
            max_value=data.get("max_price"),
            order=data.get("order"),
            tags=parse_tag_ids(data.get("tags")),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="Filter items by preparation time",
    description="Returns menu items filtered by preparation time or sorted accordingly.",
    parameters=[ItemPreparationTimeQuerySerializer],
)
class ItemByPreparationTimeListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        query = ItemPreparationTimeQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        return menu_bll.get_items_by_preparation_time(
            branch_id=self.kwargs["branch_id"],
            min_value=data.get("min_preparation_time"),
            max_value=data.get("max_preparation_time"),
            order=data.get("order"),
            tags=parse_tag_ids(data.get("tags")),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="Filter items by calories",
    description="Returns menu items filtered by calorie range or sorted by calories.",
    parameters=[ItemCalorieQuerySerializer],
)
class ItemByCalorieListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        query = ItemCalorieQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        return menu_bll.get_items_by_calories(
            branch_id=self.kwargs["branch_id"],
            min_value=data.get("min_calories"),
            max_value=data.get("max_calories"),
            order=data.get("order"),
            tags=parse_tag_ids(data.get("tags")),
        )


@extend_schema(
    tags=["Menu - Browse"],
    summary="Filter items by discount",
    description="Returns menu items filtered by discount availability or discount percentage.",
    parameters=[ItemDiscountQuerySerializer],
)
class ItemByDiscountListView(MenuBrowseTenantSummaryMixin, ListAPIView):
    serializer_class = MenuItemOutputSerializer
    pagination_class = MenuPagination

    def get_queryset(self):
        query = ItemDiscountQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        return menu_bll.get_items_by_discount(
            branch_id=self.kwargs["branch_id"],
            has_discount=data.get("has_discount"),
            min_value=data.get("min_discount"),
            max_value=data.get("max_discount"),
            order=data.get("order"),
            tags=parse_tag_ids(data.get("tags")),
        )
