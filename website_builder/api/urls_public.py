from django.urls import path

from website_builder.api.views.public_website import PublicWebsiteAPIView

app_name = "website_builder_public"

urlpatterns = [
    path(
        "websites/<uuid:tenant_id>/",
        PublicWebsiteAPIView.as_view(),
        name="public-website",
    ),
]
