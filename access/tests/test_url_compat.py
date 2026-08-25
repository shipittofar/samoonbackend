"""Verify RBAC URL compatibility aliases resolve to the same views as canonical paths."""
import uuid

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from access.api.views import PermissionAuditListView
from access.api.views.memberships import StaffAssignmentListCreateView


class RbacUrlCompatTests(SimpleTestCase):
    def test_access_alias_resolves_staff_assignments(self):
        tenant_id = uuid.uuid4()
        match = resolve(f"/api/access/tenants/{tenant_id}/staff-assignments/")
        self.assertEqual(match.func.view_class, StaffAssignmentListCreateView)
        self.assertEqual(str(match.kwargs["tenant_id"]), str(tenant_id))

    def test_authorization_canonical_resolves_staff_assignments(self):
        tenant_id = uuid.uuid4()
        match = resolve(f"/api/authorization/tenants/{tenant_id}/staff-assignments/")
        self.assertEqual(match.func.view_class, StaffAssignmentListCreateView)

    def test_tenants_alias_resolves_staff_assignments(self):
        tenant_id = uuid.uuid4()
        match = resolve(f"/api/tenants/{tenant_id}/staff-assignments/")
        self.assertEqual(match.func.view_class, StaffAssignmentListCreateView)

    def test_tenants_alias_resolves_permission_audit(self):
        tenant_id = uuid.uuid4()
        match = resolve(f"/api/tenants/{tenant_id}/permission-audit/")
        self.assertEqual(match.func.view_class, PermissionAuditListView)

    def test_access_and_authorization_reverse_namespaces_are_distinct(self):
        access_url = reverse(
            "access-compat:staff-assignment-list-create",
            kwargs={"tenant_id": uuid.uuid4()},
        )
        auth_url = reverse(
            "access:staff-assignment-list-create",
            kwargs={"tenant_id": uuid.uuid4()},
        )
        self.assertTrue(access_url.startswith("/api/access/"))
        self.assertTrue(auth_url.startswith("/api/authorization/"))
