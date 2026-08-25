from django.urls import include, path

from accounts.api.views.favorites import (
    FavoriteDetailView,
    FavoriteListCreateView,
    FavoriteSyncView,
)

app_name = "users"

urlpatterns = [
    path("favorites/sync/", FavoriteSyncView.as_view(), name="favorite-sync"),
    path("favorites/", FavoriteListCreateView.as_view(), name="favorite-list-create"),
    path(
        "favorites/<uuid:menu_item_id>/",
        FavoriteDetailView.as_view(),
        name="favorite-detail",
    ),
    path("addresses/", include("addresses.api.urls")),
]