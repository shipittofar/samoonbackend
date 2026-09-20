"""Django admin tests for Tenant soft-deactivation (not CASCADE hard-delete)."""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from access.models import (
    AssignmentMode,
    AssignmentStatus,
    PermissionAudit,
    PermissionAuditAction,
    Role,
    StaffAssignment,
    StaffMembership,
    StaffMembershipStatus,
)
from tenants.models import Owner, Tenant, TenantStatus

User = get_user_model()


def _make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "is_staff": True,
        "is_superuser": True,
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def _create_assignment(*, membership, role, status=AssignmentStatus.ACTIVE):
    return StaffAssignment.objects.create(
        membership=membership,
        role=role,
        all_locations=True,
        status=status,
        mode=AssignmentMode.MANAGE,
    )


class TenantAdminDeleteTests(TestCase):
    def setUp(self):
        self.admin_user = _make_user()
        owner = Owner.objects.create(user=self.admin_user)
        self.tenant = Tenant.objects.create(
            owner=owner,
            name=f"Tenant {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
        )
        self.staff_user = _make_user(is_staff=False, is_superuser=False)
        self.other_staff = _make_user(is_staff=False, is_superuser=False)
        self.manager_role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.client = Client()
        self.client.force_login(self.admin_user)

    def _delete_url(self, tenant=None):
        tenant = tenant or self.tenant
        return reverse("admin:tenants_tenant_delete", args=[tenant.id])

    def _membership(self, user=None, tenant=None):
        return StaffMembership.objects.create(
            user=user or self.staff_user,
            tenant=tenant or self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )

    def _audit(self, tenant=None):
        return PermissionAudit.objects.create(
            tenant=tenant or self.tenant,
            action=PermissionAuditAction.ASSIGNMENT_CREATED,
            metadata={"source": "test"},
        )

    def test_delete_tenant_with_no_memberships(self):
        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.INACTIVE)
        self.assertTrue(Tenant.objects.filter(id=self.tenant.id).exists())

    def test_delete_tenant_with_active_assignment(self):
        membership = self._membership()
        assignment = _create_assignment(membership=membership, role=self.manager_role)
        audit = self._audit()

        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)

        self.tenant.refresh_from_db()
        membership.refresh_from_db()
        assignment.refresh_from_db()
        audit.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.INACTIVE)
        self.assertEqual(membership.status, StaffMembershipStatus.REMOVED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())
        self.assertEqual(assignment.membership_id, membership.id)
        self.assertTrue(PermissionAudit.objects.filter(id=audit.id).exists())
        self.assertEqual(audit.tenant_id, self.tenant.id)

    def test_delete_tenant_with_revoked_assignment(self):
        membership = self._membership()
        assignment = _create_assignment(
            membership=membership,
            role=self.manager_role,
            status=AssignmentStatus.REVOKED,
        )
        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)

        membership.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_delete_tenant_with_active_and_revoked_assignments(self):
        membership = self._membership()
        active = _create_assignment(membership=membership, role=self.manager_role)
        revoked = _create_assignment(
            membership=membership,
            role=self.waiter_role,
            status=AssignmentStatus.REVOKED,
        )
        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)

        active.refresh_from_db()
        revoked.refresh_from_db()
        self.assertTrue(StaffAssignment.objects.filter(id=active.id).exists())
        self.assertEqual(revoked.status, AssignmentStatus.REVOKED)
        self.assertEqual(
            StaffAssignment.objects.filter(membership=membership).count(),
            2,
        )

    def test_delete_tenant_with_multiple_memberships(self):
        first = self._membership(user=self.staff_user)
        second = self._membership(user=self.other_staff)
        _create_assignment(membership=first, role=self.manager_role)
        _create_assignment(
            membership=second,
            role=self.waiter_role,
            status=AssignmentStatus.REVOKED,
        )

        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(second.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(StaffAssignment.objects.filter(membership__tenant=self.tenant).count(), 2)

    def test_confirmation_does_not_require_assignment_delete_perm(self):
        membership = self._membership()
        _create_assignment(
            membership=membership,
            role=self.manager_role,
            status=AssignmentStatus.REVOKED,
        )
        response = self.client.get(self._delete_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "doesn't have permission to delete")
        self.assertNotContains(response, "staff assignment")

    def test_already_inactive_tenant_is_idempotent(self):
        self.tenant.status = TenantStatus.INACTIVE
        self.tenant.save(update_fields=["status"])
        membership = self._membership()
        assignment = _create_assignment(membership=membership, role=self.manager_role)

        response = self.client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        membership.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.INACTIVE)
        self.assertEqual(membership.status, StaffMembershipStatus.REMOVED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_insufficient_permissions_cannot_delete_tenant(self):
        limited = _make_user(is_superuser=False, is_staff=True)
        view_perm = Permission.objects.get(
            content_type__app_label="tenants",
            codename="view_tenant",
        )
        limited.user_permissions.add(view_perm)
        client = Client()
        client.force_login(limited)

        response = client.post(self._delete_url(), {"post": "yes"})
        self.assertIn(response.status_code, (403, 302))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.ACTIVE)

    def test_delete_allowed_without_delete_staffassignment_permission(self):
        limited = _make_user(is_superuser=False, is_staff=True)
        perms = Permission.objects.filter(
            content_type__app_label="tenants",
            codename__in=["view_tenant", "delete_tenant"],
        )
        limited.user_permissions.add(*perms)
        membership = self._membership()
        assignment = _create_assignment(
            membership=membership,
            role=self.manager_role,
            status=AssignmentStatus.REVOKED,
        )
        client = Client()
        client.force_login(limited)

        response = client.post(self._delete_url(), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.INACTIVE)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_bulk_delete_follows_same_lifecycle(self):
        other_owner_user = _make_user()
        other_owner = Owner.objects.create(user=other_owner_user)
        other = Tenant.objects.create(
            owner=other_owner,
            name=f"Other {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
        )
        membership = self._membership()
        assignment = _create_assignment(membership=membership, role=self.manager_role)
        audit = self._audit()

        changelist = reverse("admin:tenants_tenant_changelist")
        response = self.client.post(
            changelist,
            {
                "action": "delete_selected",
                "_selected_action": [str(self.tenant.id), str(other.id)],
                "post": "yes",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.tenant.refresh_from_db()
        other.refresh_from_db()
        membership.refresh_from_db()
        assignment.refresh_from_db()
        audit.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.INACTIVE)
        self.assertEqual(other.status, TenantStatus.INACTIVE)
        self.assertEqual(membership.status, StaffMembershipStatus.REMOVED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())
        self.assertTrue(PermissionAudit.objects.filter(id=audit.id).exists())
