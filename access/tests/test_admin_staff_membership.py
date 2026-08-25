"""Django admin regression tests for StaffMembership inline formsets."""
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from access.admin.access_admin import StaffMembershipAdmin
from access.models import StaffAssignment, StaffMembership, StaffMembershipStatus
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
