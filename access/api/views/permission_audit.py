from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from access.api.serializers.response.rbac import PermissionAuditSerializer
from access.authorization import RequirePermission
from access.authorization.admin_role_protection import filter_permission_audit_queryset_for_viewer
from access.models import PermissionAudit


@extend_schema(
    tags=["Access - Permission Audit"],
    summary="List permission audit entries for a tenant",
)
class PermissionAuditListView(ListAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.view"))
    serializer_class = PermissionAuditSerializer

    def get_queryset(self):
        queryset = (
            PermissionAudit.objects.filter(tenant_id=self.kwargs["tenant_id"])
            .select_related("actor", "tenant", "membership", "assignment", "permission")
            .order_by("-created_at")
        )
        return filter_permission_audit_queryset_for_viewer(
            queryset, self.request.user
        )
