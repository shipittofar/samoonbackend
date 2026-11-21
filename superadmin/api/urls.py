from django.urls import path

from . import views

app_name = "superadmin"

urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="overview"),
    path("tenants/", views.TenantListView.as_view(), name="tenant-list"),
    path("tenants/<uuid:tenant_id>/", views.TenantDetailView.as_view(), name="tenant-detail"),
    path("business-requests/", views.BusinessRequestListView.as_view(), name="business-request-list"),
    path(
        "business-requests/<uuid:request_id>/approve/",
        views.BusinessRequestApproveView.as_view(),
        name="business-request-approve",
    ),
    path(
        "business-requests/<uuid:request_id>/reject/",
        views.BusinessRequestRejectView.as_view(),
        name="business-request-reject",
    ),
    path("menu-templates/", views.MenuTemplateListCreateView.as_view(), name="menu-template-list"),
    path(
        "menu-templates/<uuid:template_id>/",
        views.MenuTemplateDetailView.as_view(),
        name="menu-template-detail",
    ),
]
