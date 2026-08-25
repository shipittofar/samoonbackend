from django.urls import path

from access.api.views.tenant_roles import PermissionCatalogListView


app_name = "access_permissions"

urlpatterns = [
    path("", PermissionCatalogListView.as_view(), name="permission-catalog"),
]
