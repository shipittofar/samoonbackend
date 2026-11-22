from django.urls import path

from .views import HomepageHeroView, PlatformConfigHistoryView, PlatformConfigView

app_name = "platform_settings"

urlpatterns = [
    path("homepage/hero/", HomepageHeroView.as_view(), name="homepage-hero"),
    path("config/", PlatformConfigView.as_view(), name="config"),
    path("config/history/", PlatformConfigHistoryView.as_view(), name="config-history"),
]
