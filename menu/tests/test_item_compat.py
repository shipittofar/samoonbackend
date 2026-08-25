"""Tests for MenuItem frontend compatibility fields and independent semantics."""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from menu.models import MenuCategory, MenuItem, Tag
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


def make_item(
    branch,
    category,
    *,
    name="Burger",
    discount=Decimal("10"),
    is_active=True,
    available=True,
):
    item = MenuItem.objects.create(
        branch=branch,
        category=category,
        name=name,
        price=Decimal("20.00"),
        discount=discount,
        is_active=is_active,
        available=available,
        preparation_time=15,
        calories=500,
    )
    tag, _ = Tag.objects.get_or_create(
        branch=branch,
        name="spicy",
        defaults={"slug": "spicy"},
    )
    item.tags.add(tag)
    return item


class MenuItemCompatResponseTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)

    def test_list_response_exposes_independent_available_and_is_active(self):
        self.item.available = False
        self.item.save(update_fields=["available"])

        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        item = response.data["results"][0]
        self.assertTrue(item["is_active"])
        self.assertFalse(item["available"])

    def test_featured_alias_returns_envelope_with_results(self):
        self.item.is_featured = True
        self.item.save(update_fields=["is_featured"])

        response = self.client.get(
            "/api/menu/items/featured/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("tenant", response.data)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)

    def test_get_detail_alias_returns_single_item(self):
        response = self.client.get(
            f"/api/menu/items/{self.item.id}/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("available", response.data)
        self.assertIn("is_active", response.data)

    def test_patch_available_only_changes_available(self):
        response = self.client.patch(
            f"/api/menu/items/{self.item.id}/?branch_id={self.branch.id}",
            {"available": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["available"])
        self.assertTrue(response.data["is_active"])

        self.item.refresh_from_db()
        self.assertFalse(self.item.available)
        self.assertTrue(self.item.is_active)

    def test_patch_is_active_only_changes_is_active(self):
        response = self.client.patch(
            f"/api/menu/items/{self.item.id}/?branch_id={self.branch.id}",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_active"])
        self.assertTrue(response.data["available"])

        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)
        self.assertTrue(self.item.available)

    def test_patch_both_fields_persist_independently(self):
        response = self.client.patch(
            f"/api/menu/items/{self.item.id}/?branch_id={self.branch.id}",
            {"available": True, "is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["available"])
        self.assertFalse(response.data["is_active"])

        self.item.refresh_from_db()
        self.assertTrue(self.item.available)
        self.assertFalse(self.item.is_active)

    def test_multipart_available_true_only_changes_available(self):
        response = self.client.patch(
            f"/api/menu/items/{self.item.id}/?branch_id={self.branch.id}",
            {"available": "true"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["available"])

        self.item.refresh_from_db()
        self.assertTrue(self.item.available)


class MenuItemVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.active_item = make_item(self.branch, self.category, name="Active Burger")
        self.inactive_item = make_item(
            self.branch,
            self.category,
            name="Inactive Burger",
            is_active=False,
        )
        self.unavailable_item = make_item(
            self.branch,
            self.category,
            name="Unavailable Burger",
            available=False,
        )

    def test_public_list_hides_inactive_items(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data["results"]}
        self.assertIn(self.active_item.name, names)
        self.assertIn(self.unavailable_item.name, names)
        self.assertNotIn(self.inactive_item.name, names)

    def test_public_list_available_filter_returns_unavailable_active_items(self):
        response = self.client.get(
            "/api/menu/items/",
            {"branch_id": str(self.branch.id), "available": "false"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data["results"]}
        self.assertEqual(names, {self.unavailable_item.name})

    def test_console_list_includes_inactive_items(self):
        response = self.client.get(
            f"/api/menu/console-menu/items/{self.branch.id}/",
        )

        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data["results"]}
        self.assertIn(self.inactive_item.name, names)

    def test_public_featured_excludes_inactive_items(self):
        self.inactive_item.is_featured = True
        self.inactive_item.save(update_fields=["is_featured"])

        response = self.client.get(
            "/api/menu/items/featured/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        ids = {item["id"] for item in response.data["results"]}
        self.assertNotIn(str(self.inactive_item.id), ids)

    def test_public_detail_hides_inactive_item(self):
        response = self.client.get(
            f"/api/menu/items/{self.inactive_item.id}/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "menu_item_not_found")

    def test_public_detail_returns_unavailable_active_item(self):
        response = self.client.get(
            f"/api/menu/items/{self.unavailable_item.id}/",
            {"branch_id": str(self.branch.id)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["available"])
        self.assertTrue(response.data["is_active"])

    def test_console_can_reactivate_inactive_item_via_is_active(self):
        response = self.client.patch(
            f"/api/menu/items/{self.inactive_item.id}/?branch_id={self.branch.id}",
            {"is_active": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["is_active"])
