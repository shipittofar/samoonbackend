from django.urls import path

from tenants.api.views.qr import QrResolveAPIView

app_name = "qr"

urlpatterns = [
    path("", QrResolveAPIView.as_view(), name="qr-resolve"),
]
