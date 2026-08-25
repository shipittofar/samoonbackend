"""Compatibility URL patterns mounted at /api/tenants/.

Mirrors tenant-scoped RBAC routes from access.api.urls without duplicating
view logic. Canonical paths remain under /api/authorization/tenants/.
"""
from django.urls import path

from access.api.views import (
    MembershipPermissionOverrideListCreateView,
    MembershipPermissionOverrideRetrieveUpdateDestroyView,
    PermissionAuditListView,
    PermissionOverrideListCreateView,
    PermissionOverrideRetrieveUpdateDestroyView,
)
from access.api.views.memberships import (
    StaffAssignmentListCreateView,
    StaffAssignmentRetrieveUpdateDestroyView,
    StaffMembershipListCreateView,
    StaffMembershipRemoveView,
    StaffMembershipRetrieveUpdateView,
)

app_name = "access_tenant_compat"

urlpatterns = [
    path(
        "<uuid:tenant_id>/staff-memberships/",
        StaffMembershipListCreateView.as_view(),
        name="staff-membership-list-create",
    ),
    path(
        "<uuid:tenant_id>/staff-memberships/<uuid:membership_id>/",
        StaffMembershipRetrieveUpdateView.as_view(),
        name="staff-membership-retrieve-update",
    ),
    path(
        "<uuid:tenant_id>/staff-memberships/<uuid:membership_id>/remove/",
        StaffMembershipRemoveView.as_view(),
        name="staff-membership-remove",
    ),
    path(
        "<uuid:tenant_id>/staff-assignments/",
        StaffAssignmentListCreateView.as_view(),
        name="staff-assignment-list-create",
    ),
    path(
        "<uuid:tenant_id>/staff-assignments/<uuid:assignment_id>/",
        StaffAssignmentRetrieveUpdateDestroyView.as_view(),
        name="staff-assignment-retrieve-delete",
    ),
    path(
        "<uuid:tenant_id>/permission-overrides/",
        PermissionOverrideListCreateView.as_view(),
        name="permission-override-list-create",
    ),
    path(
        "<uuid:tenant_id>/permission-overrides/<uuid:override_id>/",
        PermissionOverrideRetrieveUpdateDestroyView.as_view(),
        name="permission-override-retrieve-update-delete",
    ),
    path(
        "<uuid:tenant_id>/memberships/<uuid:membership_id>/permission-overrides/",
        MembershipPermissionOverrideListCreateView.as_view(),
        name="membership-permission-override-list-create",
    ),
    path(
        "<uuid:tenant_id>/memberships/<uuid:membership_id>/permission-overrides/<uuid:override_id>/",
        MembershipPermissionOverrideRetrieveUpdateDestroyView.as_view(),
        name="membership-permission-override-retrieve-update-delete",
    ),
    path(
        "<uuid:tenant_id>/permission-audit/",
        PermissionAuditListView.as_view(),
        name="permission-audit-list",
    ),
]
