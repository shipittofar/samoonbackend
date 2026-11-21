from django.urls import include, path

from access.api.views.tenant_roles import TenantRoleListView
from tenants.api.views import *
from tenants.api.views.business_request import MyBusinessRequestsView

app_name = "tenants"

urlpatterns = [
    # Business registration requests (approved by platform superusers)
    path("business-requests/", MyBusinessRequestsView.as_view(), name="my-business-requests"),
    # Tenant
    path("create/",
         TenantCreateAPIView.as_view(),
         name="tenant-create"
         ),
    # Compatibility alias — same handler as create/ (tenant provisioning wizard).
    path("provision/",
         TenantCreateAPIView.as_view(),
         name="tenant-provision"
         ),
    path("<uuid:tenant_id>/update/",
         TenantUpdateAPIView.as_view(),
         name="tenant-update"
         ),
    path("<uuid:tenant_id>/settings/",
         TenantSettingsPatchAPIView.as_view(),
         name="tenant-settings-patch"
         ),
    path("<uuid:tenant_id>/qr/",
         TenantQrRetrieveAPIView.as_view(),
         name="tenant-qr"
         ),
    path("<uuid:tenant_id>/qr/enable/",
         TenantQrEnableAPIView.as_view(),
         name="tenant-qr-enable"
         ),
    path("<uuid:tenant_id>/qr/disable/",
         TenantQrDisableAPIView.as_view(),
         name="tenant-qr-disable"
         ),
    path("<uuid:tenant_id>/qr/regenerate/",
         TenantQrRegenerateAPIView.as_view(),
         name="tenant-qr-regenerate"
         ),
    path("<uuid:tenant_id>/qr/destination/",
         TenantQrDestinationAPIView.as_view(),
         name="tenant-qr-destination"
         ),
    path("",
         TenantListAPIView.as_view(),
         name="tenant-list"
         ),
    path("console-tenants/",
         ConsoleTenantListAPIView.as_view(),
         name="console-tenant-list"
         ),
    path("<uuid:tenant_id>/",
         TenantRetrieveAPIView.as_view(),
         name="tenant-detail"
         ),
    path(
        "<uuid:tenant_id>/roles/",
        TenantRoleListView.as_view(),
        name="tenant-roles",
    ),
    path("<uuid:tenant_id>/delete/", TenantDeleteView.as_view(),
         name="tenant-delete"
         ),
    path("me/",
         TenantMeListAPIView.as_view(),
         name="tenant-me"
         ),
    path(
        "<uuid:tenant_id>/branches/<uuid:branch_id>/update/",
        BranchUpdateAPIView.as_view(),
        name="branch-update",
    ),
    path(
        "<uuid:tenant_id>/branches/",
        BranchListAPIView.as_view(),
        name="branch-list",
    ),
    path(
        "<uuid:tenant_id>/branches/<uuid:branch_id>/",
        BranchRetrieveAPIView.as_view(),
        name="branch-detail",
    ),
    path(
        "<uuid:tenant_id>/branches/<uuid:branch_id>/delete/",
        BranchDeleteView.as_view(),
        name="branch-delete",
    ),
    path(
        "branches/",
        BranchGlobalListAPIView.as_view(),
        name="branch-list-all"
    ),
    path(
        "branches/<uuid:branch_id>/",
        BranchGlobalRetrieveAPIView.as_view(),
        name="branch-retrieve-global"
    ),
    # RBAC tenant-scoped compatibility aliases (canonical: /api/authorization/tenants/...).
    path("", include("access.api.urls_tenant_compat", namespace="access-tenant-compat")),
    path("", include("website_builder.api.urls")),
]
