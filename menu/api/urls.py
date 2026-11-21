"""
URL routing for the Menu app.

Sections:
    1. Categories (public CRUD)
    2. Categories (console — scoped to the authenticated owner)
    3. Items (CRUD)
    4. Extra Groups (CRUD)
    5. Extras (CRUD)
    6. Item <-> Extra links (CRUD)
    7. Menu Browse (public, read-only filtering/sorting endpoints)
"""
from django.urls import path

from menu.api.views import *
from tenants.api.views.qr_manage import (
    MenuQrDisableAPIView,
    MenuQrEnableAPIView,
    MenuQrRegenerateAPIView,
    MenuQrRetrieveAPIView,
)

app_name = "menu"

urlpatterns = [
    # Ready-made menus (prepared by platform superusers per business type)
    path(
        "branches/<uuid:branch_id>/templates/",
        BranchMenuTemplateListView.as_view(),
        name="menu-branch-templates",
    ),
    path(
        "branches/<uuid:branch_id>/templates/<uuid:template_id>/apply/",
        BranchMenuTemplateApplyView.as_view(),
        name="menu-branch-template-apply",
    ),
    path(
        "branches/<uuid:branch_id>/qr/",
        MenuQrRetrieveAPIView.as_view(),
        name="menu-branch-qr",
    ),
    path(
        "branches/<uuid:branch_id>/qr/enable/",
        MenuQrEnableAPIView.as_view(),
        name="menu-branch-qr-enable",
    ),
    path(
        "branches/<uuid:branch_id>/qr/disable/",
        MenuQrDisableAPIView.as_view(),
        name="menu-branch-qr-disable",
    ),
    path(
        "branches/<uuid:branch_id>/qr/regenerate/",
        MenuQrRegenerateAPIView.as_view(),
        name="menu-branch-qr-regenerate",
    ),
    # -----------------------------------------------------------------
    # Tags — branch-scoped CRUD + storefront
    # -----------------------------------------------------------------
    path(
        "branches/<uuid:branch_id>/tags/",
        BranchTagListCreateView.as_view(),
        name="menu-branch-tag-list-create",
    ),
    path(
        "branches/<uuid:branch_id>/tags/<int:id>/",
        BranchTagDetailView.as_view(),
        name="menu-branch-tag-detail",
    ),
    path(
        "branches/<uuid:branch_id>/available-tags/",
        AvailableTagListView.as_view(),
        name="menu-branch-available-tags",
    ),

    # -----------------------------------------------------------------
    # Categories — public CRUD
    # -----------------------------------------------------------------
    path(
        "categories",
        MenuCategoryAllListView.as_view(),
        name="menu-category-all-list",
    ),
    path(
        "categories/bulk-insert/",
        MenuCategoryBulkCreateView.as_view(),
        name="menu-category-bulk-create",
    ),
    path(
        "categories/",
        MenuCategoryCreateView.as_view(),
        name="menu-category-create",
    ),
    path(
        "categories/<uuid:branch_id>/",
        MenuCategoryListView.as_view(),
        name="menu-category-list",
    ),
    path(
        "categories/<uuid:branch_id>/<uuid:pk>/",
        MenuCategoryDetailView.as_view(),
        name="menu-category-detail",
    ),
    path(
        "update-categories/<uuid:branch_id>/categories/<uuid:pk>/",
        MenuCategoryUpdateView.as_view(),
        name="menu-category-update",
    ),
    path(
        "delete-categories/<uuid:branch_id>/categories/<uuid:pk>/",
        MenuCategoryDeleteView.as_view(),
        name="menu-category-delete",
    ),

    # -----------------------------------------------------------------
    # Categories — console (scoped to the authenticated owner)
    # -----------------------------------------------------------------
    path(
        "console-categories/",
        ConsoleCategoryListView.as_view(),
        name="console-category-list",
    ),
    path(
        "console-categories/tenants/<uuid:tenant_id>/branches/<uuid:branch_id>/",
        ConsoleCategoryByTenantBranchListView.as_view(),
        name="console-category-by-tenant-branch",
    ),
    path(
        "console-menu/categories/<uuid:branch_id>/",
        ConsoleCategoryDetailByBranchView.as_view(),
        name="console-category-detail-by-branch",
    ),
    path(
        "console-categories/<uuid:pk>/",
        ConsoleCategoryDetailView.as_view(),
        name="console-category-detail",
    ),


    # -----------------------------------------------------------------
    # Items — CRUD
    # -----------------------------------------------------------------
    path(
        "create-items/",
        MenuItemCreateView.as_view(),
        name="menu-item-create",
    ),
    path(
        "console-menu/create-items/",
        ConsoleMenuItemCreateView.as_view(),
        name="console-menu-item-create",
    ),
    path(
        "items/bulk-insert/",
        MenuItemBulkCreateView.as_view(),
        name="menu-item-bulk-create",
    ),
    path(  # check
        "console-menu/items/<uuid:branch_id>/",
        ConsoleMenuItemListView.as_view(),
        name="console-menu-item-list",
    ),
    path(
        "<uuid:branch_id>/categories/<uuid:category_id>/items/",
        MenuItemListView.as_view(),
        name="menu-item-list",
    ),
    path(
        "<uuid:branch_id>/categories/<uuid:category_id>/items/<uuid:pk>/",
        MenuItemDetailView.as_view(),
        name="menu-item-detail",
    ),
    path(
        "update-items/<uuid:branch_id>/categories/<uuid:category_id>/items/<uuid:pk>/",
        MenuItemUpdateView.as_view(),
        name="menu-item-update",
    ),
    path(
        "delete-items/<uuid:branch_id>/categories/<uuid:category_id>/items/<uuid:pk>/",
        MenuItemDeleteView.as_view(),
        name="menu-item-delete",
    ),
    path(
        "assign-extra-groups/<uuid:branch_id>/items/<uuid:item_id>/",
        MenuItemAssignExtraGroupsView.as_view(),
        name="menu-item-assign-extra-groups",
    ),
    # Frontend aliases — GET /menu/items/?branch_id=X, PATCH/POST /menu/items/{id}/?branch_id=X
    path(
        "items/",
        MenuItemCollectionAliasView.as_view(),
        name="menu-item-alias-list",
    ),
    path(
        "items/featured/",
        MenuItemFeaturedAliasView.as_view(),
        name="menu-item-featured-alias",
    ),
    path(
        "items/popular/",
        MenuItemPopularAliasView.as_view(),
        name="menu-item-popular-alias",
    ),
    path(
        "items/search/",
        MenuItemSearchAliasView.as_view(),
        name="menu-item-search-alias",
    ),
    path(
        "items/branches/<uuid:branch_id>/",
        MenuItemAliasListView.as_view(),
        name="menu-item-alias-list-by-branch",
    ),
    path(
        "items/<uuid:pk>/related/",
        MenuItemRelatedAliasView.as_view(),
        name="menu-item-related-alias",
    ),
    path(
        "items/<uuid:pk>/",
        MenuItemDetailAliasView.as_view(),
        name="menu-item-detail-alias",
    ),

    # -----------------------------------------------------------------
    # Extra Groups — CRUD
    # -----------------------------------------------------------------
    path(
        "create-extra-groups/",
        ExtraGroupCreateView.as_view(),
        name="menu-extra-group-create",
    ),
    path(
        "<uuid:branch_id>/extra-groups/",
        ExtraGroupListView.as_view(),
        name="menu-extra-group-list",
    ),
    path(
        "console-menu/extra-groups/<uuid:branch_id>/",
        ConsoleExtraGroupListView.as_view(),
        name="console-menu-extra-group-list",
    ),
    path(
        "<uuid:branch_id>/extra-groups/reorder/",
        ExtraGroupReorderView.as_view(),
        name="menu-extra-group-reorder",
    ),
    path(
        "<uuid:branch_id>/extra-groups/<uuid:pk>/",
        ExtraGroupDetailView.as_view(),
        name="menu-extra-group-detail",
    ),
    path(
        "update-extra-groups/<uuid:branch_id>/extra-groups/<uuid:pk>/",
        ExtraGroupUpdateView.as_view(),
        name="menu-extra-group-update",
    ),
    path(
        "delete-extra-groups/<uuid:branch_id>/extra-groups/<uuid:pk>/",
        ExtraGroupDeleteView.as_view(),
        name="menu-extra-group-delete",
    ),
    # Frontend aliases — /menu/extra-groups/?branch_id=X
    path(
        "extra-groups/",
        ExtraGroupCollectionAliasView.as_view(),
        name="menu-extra-group-collection-alias",
    ),
    path(
        "extra-groups/<uuid:pk>/",
        ExtraGroupDetailAliasView.as_view(),
        name="menu-extra-group-detail-alias",
    ),

    # -----------------------------------------------------------------
    # Extras — CRUD
    # -----------------------------------------------------------------
    path(
        "create-extras/",
        ExtraCreateView.as_view(),
        name="menu-extra-create",
    ),
    path(
        "<uuid:branch_id>/extras/",
        ExtraListView.as_view(),
        name="menu-extra-list",
    ),
    path(
        "<uuid:branch_id>/extras/<uuid:pk>/",
        ExtraDetailView.as_view(),
        name="menu-extra-detail",
    ),
    path(
        "update-extera/<uuid:branch_id>/extras/<uuid:pk>/",
        ExtraUpdateView.as_view(),
        name="menu-extra-update",
    ),
    path(
        "delete-exteras/<uuid:branch_id>/extras/<uuid:pk>/",
        ExtraDeleteView.as_view(),
        name="menu-extra-delete",
    ),
    # Frontend aliases — /menu/extras/?branch_id=X
    path(
        "extras/",
        ExtraCollectionAliasView.as_view(),
        name="menu-extra-collection-alias",
    ),
    path(
        "extras/<uuid:pk>/",
        ExtraDetailAliasView.as_view(),
        name="menu-extra-detail-alias",
    ),

    # -----------------------------------------------------------------
    # Item <-> Extra links — CRUD
    # -----------------------------------------------------------------
    path(
        "extras/attach/<uuid:branch_id>/items/<uuid:item_id>/",
        MenuItemExtraCreateView.as_view(),
        name="menu-item-extra-create",
    ),
    path(
        "<uuid:branch_id>/items/<uuid:item_id>/extras/",
        MenuItemExtraListView.as_view(),
        name="menu-item-extra-list",
    ),
    path(
        "update-item-extera/<uuid:branch_id>/items/<uuid:item_id>/extras/<uuid:extra_id>/",
        MenuItemExtraUpdateView.as_view(),
        name="menu-item-extra-update",
    ),
    path(
        "delete-item-extera/<uuid:branch_id>/items/<uuid:item_id>/extras/<uuid:extra_id>/",
        MenuItemExtraDeleteView.as_view(),
        name="menu-item-extra-delete",
    ),

    # -----------------------------------------------------------------
    # Menu Browse — public, read-only filtering/sorting endpoints
    # -----------------------------------------------------------------
    path(
        "<uuid:branch_id>/categories-with-items/",
        CategoryWithItemsListView.as_view(),
        name="menu-categories-with-items",
    ),
    path(
        "<uuid:branch_id>/items/popular/",
        PopularItemListView.as_view(),
        name="menu-items-popular",
    ),
    path(
        "<uuid:branch_id>/items/featured/",
        FeaturedItemListView.as_view(),
        name="menu-items-featured",
    ),
    path(
        "<uuid:branch_id>/items/active/",
        ActiveItemListView.as_view(),
        name="menu-items-active",
    ),
    path(
        "<uuid:branch_id>/items/by-price/",
        ItemByPriceListView.as_view(),
        name="menu-items-by-price",
    ),
    path(
        "<uuid:branch_id>/items/by-preparation-time/",
        ItemByPreparationTimeListView.as_view(),
        name="menu-items-by-preparation-time",
    ),
    path(
        "<uuid:branch_id>/items/by-calories/",
        ItemByCalorieListView.as_view(),
        name="menu-items-by-calories",
    ),
    path(
        "<uuid:branch_id>/items/by-discount/",
        ItemByDiscountListView.as_view(),
        name="menu-items-by-discount",
    ),
]
