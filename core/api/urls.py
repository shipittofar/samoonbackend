from django.urls import path
from core.api.views import geo_country, health_check


app_name = 'core'

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("geo/country/", geo_country, name="geo-country"),
]