from django.urls import path

from .views import HomepageHeroView

app_name = "platform_settings"

urlpatterns = [
    path("homepage/hero/", HomepageHeroView.as_view(), name="homepage-hero"),
]
