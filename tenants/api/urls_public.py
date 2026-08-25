from django.urls import include, path

from tenants.api.views.discover import DiscoverListAPIView

app_name = "public"

urlpatterns = [
    path(
        "discover/",
        DiscoverListAPIView.as_view(),
        name="discover-list",
    ),
    path("", include("website_builder.api.urls_public")),
]
