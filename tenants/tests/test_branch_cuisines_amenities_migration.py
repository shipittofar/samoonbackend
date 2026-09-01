"""Data migration: tenant marketplace cuisines/amenities → all branches."""
import importlib
import uuid

from django.apps import apps
from django.test import TestCase

from accounts.models import User
from tenants.models import Branch, Owner, Tenant


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def _migration_copy_fn():
    module = importlib.import_module(
        "tenants.migrations.0007_branch_cuisines_amenities"
    )
    return module.copy_tenant_marketplace_cuisines_amenities_to_all_branches


class BranchCuisinesAmenitiesMigrationTests(TestCase):
    def test_legacy_tenant_marketplace_values_copied_to_all_branches(self):
        owner = Owner.objects.create(user=make_user())
        tenant = Tenant.objects.create(
            owner=owner,
            name="Multi Branch Tenant",
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "marketplace": {
                    "cuisines": ["Italian", "Pizza"],
                    "amenities": ["WiFi", "Parking"],
                    "rating": 4.5,
                }
            }
        )
        branch_a = Branch.objects.create(tenant=tenant, name="Branch A")
        branch_b = Branch.objects.create(tenant=tenant, name="Branch B", is_default=True)
        branch_c = Branch.objects.create(tenant=tenant, name="Branch C")

        copy_fn = _migration_copy_fn()
        copy_fn(apps, None)

        for branch in (branch_a, branch_b, branch_c):
            branch.refresh_from_db()
            self.assertEqual(branch.cuisines, ["Italian", "Pizza"])
            self.assertEqual(branch.amenities, ["WiFi", "Parking"])

    def test_tenant_without_marketplace_cuisines_leaves_branches_unchanged(self):
        owner = Owner.objects.create(user=make_user())
        tenant = Tenant.objects.create(
            owner=owner,
            name="No Cuisines Tenant",
            settings={"marketplace": {"rating": 4.0}},
        )
        branch = Branch.objects.create(
            tenant=tenant,
            name="Only Branch",
            cuisines=["Sushi"],
            amenities=["Outdoor Seating"],
        )

        copy_fn = _migration_copy_fn()
        copy_fn(apps, None)

        branch.refresh_from_db()
        self.assertEqual(branch.cuisines, ["Sushi"])
        self.assertEqual(branch.amenities, ["Outdoor Seating"])

    def test_partial_marketplace_values_copy_only_present_keys(self):
        owner = Owner.objects.create(user=make_user())
        tenant = Tenant.objects.create(
            owner=owner,
            name="Cuisines Only Tenant",
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"marketplace": {"cuisines": ["Mexican"]}},
        )
        branch = Branch.objects.create(tenant=tenant, name="Branch")

        copy_fn = _migration_copy_fn()
        copy_fn(apps, None)

        branch.refresh_from_db()
        self.assertEqual(branch.cuisines, ["Mexican"])
        self.assertEqual(branch.amenities, [])
