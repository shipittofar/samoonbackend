"""Phase 5F: Branch Admin exposes Branch.cuisines and Branch.amenities."""
import json
import uuid

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from accounts.models import User
from tenants.admin.tenant import BranchAdmin, BranchInline
from tenants.models import Branch, BranchStatus, BranchType, Owner, Tenant


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
        "is_staff": True,
        "is_superuser": True,
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant(**kwargs):
    defaults = {
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": "active",
        "is_active": True,
        "settings": {"marketplace": {"tagline": "Keep listing"}},
    }
    defaults.update(kwargs)
    if "owner" not in defaults:
        defaults["owner"] = Owner.objects.create(user=make_user())
    return Tenant.objects.create(**defaults)


def branch_form_class():
    request = RequestFactory().get("/admin/tenants/branch/add/")
    request.user = make_user()
    return BranchAdmin(Branch, AdminSite()).get_form(request)


def admin_form_data(tenant, **overrides):
    data = {
        "tenant": str(tenant.pk),
        "name": "Admin Branch",
        "type": BranchType.PHYSICAL,
        "status": BranchStatus.ACTIVE,
        "is_active": "on",
        "time_zone": "UTC",
        "currency": "USD",
        "language": "en",
        "ordering_enabled": "on",
        "scheduled_delivery_enabled": "on",
        "cash_on_delivery_enabled": "on",
        "marketplace_visible": "on",
        "cuisines": json.dumps(["Persian", "Italian"]),
        "amenities": json.dumps(["WiFi", "Parking"]),
        "settings": json.dumps({}),
        "metadata": json.dumps({}),
    }
    data.update(overrides)
    return data


class BranchAdminCuisinesAmenitiesTests(TestCase):
    def test_cuisines_and_amenities_appear_in_branch_admin_fieldsets(self):
        fields = []
        for _name, opts in BranchAdmin.fieldsets:
            fields.extend(opts["fields"])
        self.assertIn("cuisines", fields)
        self.assertIn("amenities", fields)

    def test_branch_inline_does_not_include_json_list_fields(self):
        self.assertNotIn("cuisines", BranchInline.fields)
        self.assertNotIn("amenities", BranchInline.fields)

    def test_admin_can_create_branch_with_cuisines_and_amenities(self):
        tenant = make_tenant()
        form = branch_form_class()(data=admin_form_data(tenant))
        self.assertTrue(form.is_valid(), form.errors)
        branch = form.save()
        self.assertEqual(branch.cuisines, ["Persian", "Italian"])
        self.assertEqual(branch.amenities, ["WiFi", "Parking"])

    def test_admin_can_edit_cuisines_and_amenities(self):
        tenant = make_tenant()
        branch = Branch.objects.create(
            tenant=tenant,
            name="Existing",
            city="Rome",
            ordering_enabled=True,
            cuisines=["Old"],
            amenities=["Old Amenity"],
        )
        form = branch_form_class()(
            data=admin_form_data(
                tenant,
                name="Existing",
                city="Rome",
                cuisines=json.dumps(["Persian"]),
                amenities=json.dumps(["WiFi"]),
            ),
            instance=branch,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        branch.refresh_from_db()
        self.assertEqual(branch.cuisines, ["Persian"])
        self.assertEqual(branch.amenities, ["WiFi"])
        self.assertEqual(branch.city, "Rome")
        self.assertTrue(branch.ordering_enabled)

    def test_existing_json_lists_load_in_admin_form(self):
        tenant = make_tenant()
        branch = Branch.objects.create(
            tenant=tenant,
            name="Loaded",
            cuisines=["Persian", "Italian"],
            amenities=["WiFi", "Parking"],
        )
        form = branch_form_class()(instance=branch)
        self.assertEqual(form.initial["cuisines"], ["Persian", "Italian"])
        self.assertEqual(form.initial["amenities"], ["WiFi", "Parking"])

    def test_admin_save_does_not_modify_tenant_settings(self):
        tenant = make_tenant()
        original = dict(tenant.settings)
        form = branch_form_class()(data=admin_form_data(tenant))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings, original)
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Keep listing")
        self.assertNotIn("cuisines", tenant.settings.get("marketplace", {}))
        self.assertNotIn("amenities", tenant.settings.get("marketplace", {}))
