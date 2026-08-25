from django.urls import path

from tenants.api.views.branch_metrics import BranchMetricsAPIView
from tenants.api.views import BranchCreateAPIView, BranchConsoleUpdateAPIView, ConsoleBranchDeleteView

app_name = "branches"

urlpatterns = [
    path(
        "<uuid:branch_id>/",
        BranchConsoleUpdateAPIView.as_view(),
        name="branch-console-update",
    ),
    path(
        "console-branches/<uuid:branch_id>/metrics/",
        BranchMetricsAPIView.as_view(),
        name="console-branch-metrics",
    ),
    path(
        "console-branches/tenants/<uuid:tenant_id>/create/",
        BranchCreateAPIView.as_view(),
        name="branch-create",
    ),
    path(
        "console-branches/branches/<uuid:branch_id>/delete/",
        ConsoleBranchDeleteView.as_view(),
        name="branch-delete",
    ),
]
