from django.urls import path

from .views import TenantConfigHistoryView, TenantConfigView

app_name = "tenant_config"

# Mounted at /api/tenants/<tenant_id>/ (before the tenants app urls).
urlpatterns = [
    path("config/", TenantConfigView.as_view(), name="config"),
    path("config/history/", TenantConfigHistoryView.as_view(), name="config-history"),
]
