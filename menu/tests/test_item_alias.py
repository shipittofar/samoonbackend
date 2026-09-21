"""Tests for the public branch-scoped menu item alias endpoint."""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from menu.models import MenuCategory, MenuItem
from tenants.models import Tenant, Branch, Owner


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


def make_branch():
    owner = Owner.objects.create(user=make_user())
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return Branch.objects.create(tenant=tenant, name="Main")


def make_category(branch):
    return MenuCategory.objects.create(branch=branch, name="Mains")


def make_item(branch, category, *, name="Burger", is_active=True, available=True):
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name=name,
        price=Decimal("9.99"),
        is_active=is_active,
        available=available,
    )


class MenuItemAliasListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.other_branch = make_branch()
        self.category = make_category(self.branch)
        self.active_item = make_item(self.branch, self.category, name="Active Burger")
        self.inactive_item = make_item(
            self.branch, self.category, name="Inactive Burger", is_active=False
        )
        other_category = make_category(self.other_branch)
        self.other_branch_item = make_item(
            self.other_branch, other_category, name="Other Branch Burger"
        )

    def test_unauthenticated_can_list_active_items_with_query_param(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        result_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(result_ids, {str(self.active_item.id)})

    def test_unauthenticated_can_list_active_items_with_path_param(self):
        response = self.client.get(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        result_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(result_ids, {str(self.active_item.id)})

    def test_branch_path_includes_active_unavailable_items(self):
        unavailable_item = make_item(
            self.branch,
            self.category,
            name="Unavailable Burger",
            available=False,
        )

        response = self.client.get(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data["results"]}
        self.assertIn(unavailable_item.name, names)

    def test_branch_path_excludes_inactive_items(self):
        response = self.client.get(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data["results"]}
        self.assertNotIn(self.inactive_item.name, names)

    def test_branch_path_exposes_independent_available_and_is_active(self):
        unavailable_item = make_item(
            self.branch,
            self.category,
            name="Unavailable Burger",
            available=False,
        )

        response = self.client.get(f"/api/menu/items/branches/{self.branch.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        by_id = {item["id"]: item for item in response.data["results"]}
        item = by_id[str(unavailable_item.id)]
        self.assertTrue(item["is_active"])
        self.assertFalse(item["available"])

    def test_inactive_items_are_excluded(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        names = {item["name"] for item in response.data["results"]}
        self.assertNotIn(self.inactive_item.name, names)

    def test_items_from_other_branches_are_excluded(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        names = {item["name"] for item in response.data["results"]}
        self.assertNotIn(self.other_branch_item.name, names)

    def test_unknown_branch_returns_error(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_response_includes_expected_menu_item_fields(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        item = response.data["results"][0]
        for field in (
            "id",
            "branch_id",
            "category_id",
            "name",
            "slug",
            "price",
            "is_active",
            "available",
            "rating",
            "rating_count",
            "discounted_price",
            "extras",
            "tags",
            "extra_group_ids",
        ):
            self.assertIn(field, item)

    def test_item_assign_alias_route_is_not_used_for_listing(self):
        # Path is the detail alias (items/<uuid:pk>/), not a branch listing.
        # Passing a branch id yields a client error (not a listing response).
        response = self.client.get(f"/api/menu/items/{self.branch.id}/")

        self.assertEqual(response.status_code, 400)


class MenuItemDetailAliasViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category, name="Burger")
        self.client.force_authenticate(user=self.branch.tenant.owner.user)

    def _item_url(self, item_id):
        return f"/api/menu/items/{item_id}/?branch_id={self.branch.id}"

    def test_patch_updates_menu_item(self):
        response = self.client.patch(
            self._item_url(self.item.id),
            {"name": "Updated Burger", "price": "12.50"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["name"], "Updated Burger")
        self.assertEqual(response.data["price"], "12.50")

        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Updated Burger")

    def test_post_updates_menu_item_same_as_patch(self):
        patch_response = self.client.patch(
            self._item_url(self.item.id),
            {"name": "Patch Name"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.data)

        other_branch = make_branch()
        other_category = make_category(other_branch)
        other_item = make_item(other_branch, other_category, name="Other")
        self.client.force_authenticate(user=other_branch.tenant.owner.user)

        post_response = self.client.post(
            f"/api/menu/items/{other_item.id}/?branch_id={other_branch.id}",
            {"name": "Post Name"},
            format="json",
        )

        self.assertEqual(post_response.status_code, 200, post_response.data)
        self.assertEqual(post_response.data["name"], "Post Name")
        self.assertEqual(post_response.data["id"], str(other_item.id))

    def test_post_returns_same_structure_as_patch(self):
        payload = {"description": "Tasty burger"}
        patch_response = self.client.patch(
            self._item_url(self.item.id),
            payload,
            format="json",
        )
        post_response = self.client.post(
            self._item_url(self.item.id),
            payload,
            format="json",
        )

        self.assertEqual(patch_response.status_code, 200, patch_response.data)
        self.assertEqual(post_response.status_code, 200, post_response.data)
        self.assertEqual(set(patch_response.data.keys()), set(post_response.data.keys()))

    def test_unknown_item_returns_not_found(self):
        response = self.client.post(
            f"/api/menu/items/{uuid.uuid4()}/?branch_id={self.branch.id}",
            {"name": "Missing"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "menu_item_not_found")

    def test_validation_error_returns_400(self):
        response = self.client.post(
            self._item_url(self.item.id),
            {"price": "not-a-number"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class MenuItemAvailableDefaultTests(TestCase):
    def test_menu_item_defaults_available_to_true(self):
        branch = make_branch()
        category = make_category(branch)
        item = MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Default Availability Burger",
            price=Decimal("9.99"),
        )

        self.assertTrue(item.available)
