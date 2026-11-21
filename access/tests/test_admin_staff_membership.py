"""Django admin regression tests for StaffMembership inline formsets."""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from access.admin.access_admin import StaffMembershipAdmin
from access.models import (
    AssignmentMode,
    AssignmentStatus,
    Role,
    StaffAssignment,
    StaffMembership,
    StaffMembershipStatus,
)
from tenants.models import Owner, Tenant

User = get_user_model()


class _PreSaveFormset:
    """Minimal stand-in for an inline formset before save() runs."""

    def __init__(self, *, model, deleted_forms=None, changed=False):
        self.model = model
        self.deleted_forms = deleted_forms or []
        self._changed = changed

    def has_changed(self):
        return self._changed

    def save(self):
        self.new_objects = []
        self.changed_objects = []
        self.deleted_objects = []
        return []


class StaffMembershipAdminSaveFormsetTests(TestCase):
    def test_save_formset_without_deleted_objects_attribute(self):
        admin = StaffMembershipAdmin(StaffMembership, None)
        formset = _PreSaveFormset(model=StaffAssignment)

        admin.save_formset(None, None, formset, change=False)

    def test_save_formset_blocks_inline_changes(self):
        admin = StaffMembershipAdmin(StaffMembership, None)
        formset = _PreSaveFormset(model=StaffAssignment, changed=True)

        with self.assertRaises(PermissionDenied):
            admin.save_formset(None, None, formset, change=True)


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


class StaffMembershipAdminIntegrationTests(TestCase):
    def setUp(self):
        self.admin_user = _make_user()
        self.staff_user = _make_user()
        owner = Owner.objects.create(user=self.admin_user)
        self.tenant = Tenant.objects.create(owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}")
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_add_staff_membership_page_renders(self):
        response = self.client.get(reverse("admin:access_staffmembership_add"))
        self.assertEqual(response.status_code, 200)

    def test_create_staff_membership_with_empty_assignment_inline(self):
        response = self.client.post(
            reverse("admin:access_staffmembership_add"),
            {
                "user": str(self.staff_user.id),
                "tenant": str(self.tenant.id),
                "status": StaffMembershipStatus.ACTIVE,
                "assignments-TOTAL_FORMS": "0",
                "assignments-INITIAL_FORMS": "0",
                "assignments-MIN_NUM_FORMS": "0",
                "assignments-MAX_NUM_FORMS": "1000",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StaffMembership.objects.filter(
                user=self.staff_user,
                tenant=self.tenant,
            ).exists()
        )


def _create_assignment(*, membership, role, status=AssignmentStatus.ACTIVE):
    return StaffAssignment.objects.create(
        membership=membership,
        role=role,
        all_locations=True,
        status=status,
        mode=AssignmentMode.MANAGE,
    )


class StaffMembershipAdminDeleteTests(TestCase):
    def setUp(self):
        self.admin_user = _make_user()
        self.staff_user = _make_user(is_staff=False, is_superuser=False)
        owner = Owner.objects.create(user=self.admin_user)
        self.tenant = Tenant.objects.create(owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.client = Client()
        self.client.force_login(self.admin_user)

    def _changelist_remove(self, membership=None):
        membership = membership or self.membership
        return self.client.post(
            reverse("admin:access_staffmembership_changelist"),
            {
                "action": "remove_selected_memberships",
                "_selected_action": [str(membership.id)],
            },
        )

    def test_delete_membership_with_active_assignment_soft_removes(self):
        assignment = _create_assignment(membership=self.membership, role=self.role)
        response = self._changelist_remove()
        self.assertEqual(response.status_code, 302)

        self.membership.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertEqual(assignment.membership_id, self.membership.id)

    def test_delete_membership_with_revoked_assignment_keeps_audit_row(self):
        assignment = _create_assignment(
            membership=self.membership,
            role=self.role,
            status=AssignmentStatus.REVOKED,
        )
        response = self._changelist_remove()
        self.assertEqual(response.status_code, 302)

        self.membership.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_delete_membership_with_active_and_revoked_assignments(self):
        active = _create_assignment(membership=self.membership, role=self.role)
        revoked = _create_assignment(
            membership=self.membership,
            role=self.waiter_role,
            status=AssignmentStatus.REVOKED,
        )
        response = self._changelist_remove()
        self.assertEqual(response.status_code, 302)

        self.membership.refresh_from_db()
        active.refresh_from_db()
        revoked.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
        self.assertEqual(active.status, AssignmentStatus.REVOKED)
        self.assertEqual(revoked.status, AssignmentStatus.REVOKED)
        self.assertEqual(StaffAssignment.objects.filter(membership=self.membership).count(), 2)

    def test_delete_confirmation_does_not_require_assignment_delete_perm(self):
        _create_assignment(
            membership=self.membership,
            role=self.role,
            status=AssignmentStatus.REVOKED,
        )
        admin = StaffMembershipAdmin(StaffMembership, None)
        request = type("R", (), {"user": self.admin_user})()
        deleted_objects, _model_count, perms_needed, protected = admin.get_deleted_objects(
            [self.membership], request
        )
        self.assertEqual(perms_needed, set())
        self.assertEqual(protected, [])
        self.assertFalse(admin.has_delete_permission(request, self.membership))
        blob = " ".join(deleted_objects).lower()
        self.assertNotIn("staff assignment", blob)

    def test_already_removed_membership_is_skipped(self):
        self.membership.status = StaffMembershipStatus.REMOVED
        self.membership.save(update_fields=["status"])
        response = self._changelist_remove()
        self.assertEqual(response.status_code, 302)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
        self.assertTrue(StaffMembership.objects.filter(id=self.membership.id).exists())

    def test_insufficient_permissions_cannot_delete_membership(self):
        limited = _make_user(is_superuser=False, is_staff=True)
        view_perm = Permission.objects.get(
            content_type__app_label="access",
            codename="view_staffmembership",
        )
        limited.user_permissions.add(view_perm)
        client = Client()
        client.force_login(limited)

        response = client.post(
            reverse("admin:access_staffmembership_changelist"),
            {
                "action": "remove_selected_memberships",
                "_selected_action": [str(self.membership.id)],
            },
        )
        self.assertIn(response.status_code, (403, 302))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.ACTIVE)

    def test_delete_allowed_without_delete_staffassignment_permission(self):
        # The Django admin is for superusers only; the point here is that the
        # action does not need delete permission on staff assignments.
        limited = _make_user(is_superuser=True, is_staff=True)
        perms = Permission.objects.filter(
            content_type__app_label="access",
            codename__in=[
                "view_staffmembership",
                "change_staffmembership",
                "view_staffassignment",
            ],
        )
        limited.user_permissions.add(*perms)
        _create_assignment(
            membership=self.membership,
            role=self.role,
            status=AssignmentStatus.REVOKED,
        )
        client = Client()
        client.force_login(limited)

        response = client.post(
            reverse("admin:access_staffmembership_changelist"),
            {
                "action": "remove_selected_memberships",
                "_selected_action": [str(self.membership.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, StaffMembershipStatus.REMOVED)
