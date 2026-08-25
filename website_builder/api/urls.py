from django.urls import path

from website_builder.api.views import (
    BranchWebsiteOverridesAPIView,
    WebsiteLayoutAPIView,
    WebsiteMediaUploadAPIView,
)

app_name = "website_builder"

urlpatterns = [
    path(
        "<uuid:tenant_id>/website/layout/",
        WebsiteLayoutAPIView.as_view(),
        name="website-layout",
    ),
    path(
        "<uuid:tenant_id>/branches/<uuid:branch_id>/website/overrides/",
        BranchWebsiteOverridesAPIView.as_view(),
        name="branch-website-overrides",
    ),
    path(
        "<uuid:tenant_id>/website/media/",
        WebsiteMediaUploadAPIView.as_view(),
        name="website-media-upload",
    ),
]
