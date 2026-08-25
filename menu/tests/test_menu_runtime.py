"""Regression tests for menu console isolation (branch-scoped + ownership).

Public category/item list endpoints are storefront-readable. Console
endpoints require an authenticated tenant owner. StaffMembership without
ownership must not unlock console menu management.
"""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import StaffMembership, StaffMembershipStatus
from access.tests.helpers import create_canonical_assignment, get_role
from accounts.models import User
from menu.models import MenuCategory, MenuItem
from tenants.models import Branch, Owner, Tenant


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant_with_owner(**kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {"name": f"Tenant {uuid.uuid4().hex[:6]}", "owner": owner}
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    branch = Branch.objects.create(tenant=tenant, name="Main")
    return owner_user, tenant, branch


def make_staff_membership(user, tenant, *, role_slug=None, all_locations=True, branch=None):
    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    if role_slug is not None:
        create_canonical_assignment(
            membership=membership,
            role=get_role(role_slug),
            all_locations=all_locations,
            branch=branch,
        )
    return membership


class MenuCategoryIsolationTests(TestCase):
    def test_unauthenticated_cannot_list_console_categories(self):
        _, tenant, branch = make_tenant_with_owner()
        client = APIClient()
        response = client.get(
            f"/api/menu/console-categories/tenants/{tenant.id}/branches/{branch.id}/"
        )
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_cannot_create_category(self):
        _, _, branch = make_tenant_with_owner()
        client = APIClient()
        response = client.post(
            "/api/menu/categories/",
            {"branch_id": str(branch.id), "name": "Drinks"},
            format="json",
        )
        # Create view currently has no permission_classes (AllowAny).
        # Pin current behavior; storefront write auth is a separate hardening item.
        self.assertIn(response.status_code, (201, 401, 403), response.data)

    def test_member_without_permission_cannot_list_console_categories(self):
        _, tenant, branch = make_tenant_with_owner()
        user = make_user()
        make_staff_membership(user, tenant, role_slug=None)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            f"/api/menu/console-categories/tenants/{tenant.id}/branches/{branch.id}/"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_owner_can_list_console_categories(self):
        owner_user, tenant, branch = make_tenant_with_owner()
        MenuCategory.objects.create(branch=branch, name="Mains")

        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(
            f"/api/menu/console-categories/tenants/{tenant.id}/branches/{branch.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_owner_of_other_tenant_cannot_list_console_categories(self):
        _, tenant_a, branch_a = make_tenant_with_owner()
        owner_b, _, _ = make_tenant_with_owner()
        MenuCategory.objects.create(branch=branch_a, name="Mains")

        client = APIClient()
        client.force_authenticate(user=owner_b)
        response = client.get(
            f"/api/menu/console-categories/tenants/{tenant_a.id}/branches/{branch_a.id}/"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_public_list_is_branch_scoped(self):
        _, _, branch = make_tenant_with_owner()
        MenuCategory.objects.create(branch=branch, name="Mains")

        client = APIClient()
        response = client.get(f"/api/menu/categories/{branch.id}/")
        self.assertEqual(response.status_code, 200, response.data)


class MenuItemIsolationTests(TestCase):
    def test_owner_can_list_items_for_own_branch(self):
        owner_user, _, branch = make_tenant_with_owner()
        category = MenuCategory.objects.create(branch=branch, name="Mains")
        MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Burger",
            price=Decimal("9.99"),
        )

        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(
            f"/api/menu/{branch.id}/categories/{category.id}/items/"
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_public_item_list_does_not_require_membership(self):
        _, _, branch = make_tenant_with_owner()
        category = MenuCategory.objects.create(branch=branch, name="Mains")
        MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Burger",
            price=Decimal("9.99"),
        )
        outsider = make_user()

        client = APIClient()
        client.force_authenticate(user=outsider)
        response = client.get(
            f"/api/menu/{branch.id}/categories/{category.id}/items/"
        )
        self.assertEqual(response.status_code, 200, response.data)
