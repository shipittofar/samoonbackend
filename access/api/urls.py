from django.urls import path

from access.api.views import (
    PermissionListView,
    PermissionRetrieveView,
    RoleListCreateView,
    RolePermissionManageView,
    RoleRetrieveDestroyView,
    PermissionOverrideListCreateView,
    PermissionOverrideRetrieveUpdateDestroyView,
    MembershipPermissionOverrideListCreateView,
    MembershipPermissionOverrideRetrieveUpdateDestroyView,
    PermissionAuditListView,
)
from access.api.views.memberships import (
    StaffAssignmentListCreateView,
    StaffAssignmentRetrieveUpdateDestroyView,
    StaffMembershipListCreateView,
    StaffMembershipRemoveView,
    StaffMembershipRetrieveUpdateView,
    SwitchActiveTenantAPIView,
    SwitchActiveBranchAPIView,
)


app_name = 'access'
urlpatterns = [
    path("roles/", RoleListCreateView.as_view(), name="role-list-create"),
    path("roles/<uuid:role_id>/", RoleRetrieveDestroyView.as_view(), name="role-retrieve-delete"),
    path("roles/<uuid:role_id>/permissions/", RolePermissionManageView.as_view(), name="role-permission-manage"),
    path("permissions/", PermissionListView.as_view(), name="permission-list"),
    path("permissions/<uuid:permission_id>/", PermissionRetrieveView.as_view(), name="permission-retrieve"),

    path(
        "tenants/<uuid:tenant_id>/staff-memberships/",
        StaffMembershipListCreateView.as_view(),
        name="staff-membership-list-create",
    ),
    path(
        "tenants/<uuid:tenant_id>/staff-memberships/<uuid:membership_id>/",
        StaffMembershipRetrieveUpdateView.as_view(),
        name="staff-membership-retrieve-update",
    ),
    path(
        "tenants/<uuid:tenant_id>/staff-memberships/<uuid:membership_id>/remove/",
        StaffMembershipRemoveView.as_view(),
        name="staff-membership-remove",
    ),
    path(
        "tenants/<uuid:tenant_id>/staff-assignments/",
        StaffAssignmentListCreateView.as_view(),
        name="staff-assignment-list-create",
    ),
    path(
        "tenants/<uuid:tenant_id>/staff-assignments/<uuid:assignment_id>/",
        StaffAssignmentRetrieveUpdateDestroyView.as_view(),
        name="staff-assignment-retrieve-delete",
    ),
    path(
        "tenants/<uuid:tenant_id>/permission-overrides/",
        PermissionOverrideListCreateView.as_view(),
        name="permission-override-list-create",
    ),
    path(
        "tenants/<uuid:tenant_id>/permission-overrides/<uuid:override_id>/",
        PermissionOverrideRetrieveUpdateDestroyView.as_view(),
        name="permission-override-retrieve-update-delete",
    ),
    path(
        "tenants/<uuid:tenant_id>/memberships/<uuid:membership_id>/permission-overrides/",
        MembershipPermissionOverrideListCreateView.as_view(),
        name="membership-permission-override-list-create",
    ),
    path(
        "tenants/<uuid:tenant_id>/memberships/<uuid:membership_id>/permission-overrides/<uuid:override_id>/",
        MembershipPermissionOverrideRetrieveUpdateDestroyView.as_view(),
        name="membership-permission-override-retrieve-update-delete",
    ),
    path(
        "tenants/<uuid:tenant_id>/permission-audit/",
        PermissionAuditListView.as_view(),
        name="permission-audit-list",
    ),
    path(
        "switch-tenant/",
        SwitchActiveTenantAPIView.as_view(),
        name="switch-active-tenant"
    ),
    path(
        "switch-branch/",
        SwitchActiveBranchAPIView.as_view(),
        name="switch-active-branch"
    ),

]