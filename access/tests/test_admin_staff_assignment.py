"""Django admin tests for BLL-backed StaffAssignment writes."""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from access.models import (
    AssignmentMode,
    AssignmentStatus,
    PermissionAudit,
    PermissionAuditAction,
    Role,
    StaffAssignment,
    StaffAssignmentLocation,
    StaffMembership,
    StaffMembershipStatus,
)
from tenants.models import Branch, Owner, Tenant

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


class StaffAssignmentAdminWriteTests(TestCase):
    def setUp(self):
        self.admin_user = _make_user(first_name="Ops", last_name="Admin")
        self.staff_user = _make_user(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            is_staff=False,
            is_superuser=False,
        )
        owner = Owner.objects.create(user=self.admin_user)
        self.tenant = Tenant.objects.create(
            owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}"
        )
        self.other_owner = _make_user()
        other_owner_profile = Owner.objects.create(user=self.other_owner)
        self.other_tenant = Tenant.objects.create(
            owner=other_owner_profile, name=f"Other {uuid.uuid4().hex[:6]}"
        )
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(tenant=self.tenant, name="Branch A")
        self.branch_b = Branch.objects.create(tenant=self.tenant, name="Branch B")
        self.foreign_branch = Branch.objects.create(
            tenant=self.other_tenant, name="Foreign Branch"
        )
        self.manager_role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.owner_role = Role.objects.get(slug="owner")
        self.client = Client()
        self.client.force_login(self.admin_user)
        self.add_url = reverse("admin:access_staffassignment_add")
        self.changelist_url = reverse("admin:access_staffassignment_changelist")

    def _create_payload(self, **overrides):
        payload = {
            "membership": str(self.membership.id),
            "role": str(self.manager_role.id),
            "locations": [str(self.branch_a.id)],
            "mode": AssignmentMode.MANAGE,
            "valid_from": "",
            "valid_until": "",
        }
        payload.update(overrides)
        # Unchecked checkboxes are omitted from HTML posts; avoid sending "False".
        if payload.get("all_locations"):
            payload["all_locations"] = "on"
        else:
            payload.pop("all_locations", None)
        if not payload.get("locations"):
            payload.pop("locations", None)
        return payload

    def test_add_page_renders(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="owner"', html=False)
        # Owner role option must not appear in the role select.
        self.assertNotContains(response, f'value="{self.owner_role.id}"')

    def test_create_assignment_persists_locations_and_audit(self):
        response = self.client.post(self.add_url, self._create_payload())
        self.assertEqual(response.status_code, 302)

        assignment = StaffAssignment.objects.get(membership=self.membership)
        self.assertEqual(assignment.role_id, self.manager_role.id)
        self.assertFalse(assignment.all_locations)
        self.assertEqual(assignment.granted_by_id, self.admin_user.id)
        self.assertIsNotNone(assignment.granted_at)
        self.assertEqual(
            set(assignment.locations.values_list("branch_id", flat=True)),
            {self.branch_a.id},
        )
        self.assertTrue(
            PermissionAudit.objects.filter(
                action=PermissionAuditAction.ASSIGNMENT_CREATED,
                assignment_id=assignment.id,
                actor_id=self.admin_user.id,
            ).exists()
        )

    def test_create_all_locations_has_no_junction_rows(self):
        response = self.client.post(
            self.add_url,
            self._create_payload(all_locations=True, locations=[]),
        )
        self.assertEqual(response.status_code, 302)
        assignment = StaffAssignment.objects.get(membership=self.membership)
        self.assertTrue(assignment.all_locations)
        self.assertEqual(assignment.locations.count(), 0)

    def test_owner_role_rejected(self):
        response = self.client.post(
            self.add_url,
            self._create_payload(
                role=str(self.owner_role.id),
                all_locations=True,
                locations=[],
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StaffAssignment.objects.filter(membership=self.membership).exists())

    def test_foreign_branch_rejected(self):
        response = self.client.post(
            self.add_url,
            self._create_payload(locations=[str(self.foreign_branch.id)]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StaffAssignment.objects.filter(membership=self.membership).exists())

    def test_update_role_mode_dates_and_locations(self):
        create_response = self.client.post(self.add_url, self._create_payload())
        self.assertEqual(create_response.status_code, 302)
        assignment = StaffAssignment.objects.get(membership=self.membership)
        change_url = reverse(
            "admin:access_staffassignment_change", args=[assignment.id]
        )

        valid_from = timezone.now().replace(microsecond=0)
        valid_until = valid_from + timedelta(days=30)
        response = self.client.post(
            change_url,
            {
                "role": str(self.waiter_role.id),
                "locations": [str(self.branch_a.id), str(self.branch_b.id)],
                "mode": AssignmentMode.READ,
                "valid_from": valid_from.strftime("%Y-%m-%d %H:%M:%S"),
                "valid_until": valid_until.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.assertEqual(response.status_code, 302)

        assignment.refresh_from_db()
        self.assertEqual(assignment.role_id, self.waiter_role.id)
        self.assertEqual(assignment.mode, AssignmentMode.READ)
        self.assertEqual(
            set(assignment.locations.values_list("branch_id", flat=True)),
            {self.branch_a.id, self.branch_b.id},
        )
        self.assertTrue(
            PermissionAudit.objects.filter(
                action=PermissionAuditAction.ASSIGNMENT_UPDATED,
                assignment_id=assignment.id,
            ).exists()
        )

    def test_switch_to_all_locations_clears_junction_rows(self):
        self.client.post(self.add_url, self._create_payload())
        assignment = StaffAssignment.objects.get(membership=self.membership)
        change_url = reverse(
            "admin:access_staffassignment_change", args=[assignment.id]
        )

        response = self.client.post(
            change_url,
            {
                "role": str(self.manager_role.id),
                "all_locations": "on",
                "mode": AssignmentMode.MANAGE,
                "valid_from": "",
                "valid_until": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertTrue(assignment.all_locations)
        self.assertEqual(
            StaffAssignmentLocation.objects.filter(assignment=assignment).count(),
            0,
        )

    def test_hard_delete_disabled(self):
        self.client.post(self.add_url, self._create_payload())
        assignment = StaffAssignment.objects.get(membership=self.membership)
        delete_url = reverse(
            "admin:access_staffassignment_delete", args=[assignment.id]
        )
        response = self.client.post(delete_url, {"post": "yes"})
        self.assertIn(response.status_code, (403, 302, 404, 200))
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())

    def test_revoke_action_soft_revokes(self):
        self.client.post(self.add_url, self._create_payload())
        assignment = StaffAssignment.objects.get(membership=self.membership)

        response = self.client.post(
            self.changelist_url,
            {
                "action": "revoke_selected_assignments",
                "_selected_action": [str(assignment.id)],
            },
        )
        self.assertEqual(response.status_code, 302)

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
        self.assertEqual(assignment.revoked_by_id, self.admin_user.id)
        self.assertIsNotNone(assignment.revoked_at)
        self.assertTrue(StaffAssignment.objects.filter(id=assignment.id).exists())
        self.assertTrue(
            PermissionAudit.objects.filter(
                action=PermissionAuditAction.ASSIGNMENT_REVOKED,
                assignment_id=assignment.id,
                actor_id=self.admin_user.id,
            ).exists()
        )

    def test_revoked_assignment_cannot_be_edited(self):
        self.client.post(self.add_url, self._create_payload())
        assignment = StaffAssignment.objects.get(membership=self.membership)
        self.client.post(
            self.changelist_url,
            {
                "action": "revoke_selected_assignments",
                "_selected_action": [str(assignment.id)],
            },
        )
        change_url = reverse(
            "admin:access_staffassignment_change", args=[assignment.id]
        )
        response = self.client.post(
            change_url,
            {
                "role": str(self.waiter_role.id),
                "all_locations": "on",
                "mode": AssignmentMode.READ,
                "valid_from": "",
                "valid_until": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertEqual(assignment.role_id, self.manager_role.id)
        self.assertEqual(assignment.status, AssignmentStatus.REVOKED)
