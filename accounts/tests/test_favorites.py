"""Tests for user favorites API (/api/users/favorites/)."""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Favorite, User
from menu.models import MenuCategory, MenuItem
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


def make_branch():
    owner = Owner.objects.create(user=make_user())
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return Branch.objects.create(tenant=tenant, name="Main")


def make_category(branch):
    return MenuCategory.objects.create(branch=branch, name="Mains")


def make_item(branch, category, *, is_active=True, available=True):
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name=f"Item {uuid.uuid4().hex[:6]}",
        price=Decimal("9.99"),
        is_active=is_active,
        available=available,
    )


def auth_client(user):
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


class FavoriteListTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.active_item = make_item(
            self.branch, self.category, is_active=True, available=True
        )
        self.inactive_item = make_item(
            self.branch, self.category, is_active=False, available=True
        )
        self.unavailable_item = make_item(
            self.branch, self.category, is_active=True, available=False
        )
        self.soft_deleted_item = make_item(
            self.branch, self.category, is_active=True, available=True
        )
        MenuItem.objects.filter(id=self.soft_deleted_item.id).update(
            deleted_at=timezone.now()
        )

        Favorite.objects.create(user=self.user, menu_item=self.active_item)
        Favorite.objects.create(user=self.user, menu_item=self.inactive_item)
        Favorite.objects.create(user=self.user, menu_item=self.unavailable_item)
        Favorite.objects.create(user=self.user, menu_item=self.soft_deleted_item)

    def test_list_returns_paginated_envelope_with_sync(self):
        response = self.client.get("/api/users/favorites/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("sync", response.data)
        self.assertIn("version", response.data["sync"])
        self.assertIn("generated_at", response.data["sync"])
        self.assertIn("total_count", response.data["sync"])
        self.assertIn("results", response.data)
        self.assertIn("count", response.data)

    def test_list_returns_rich_favorite_objects(self):
        response = self.client.get("/api/users/favorites/")
        result = response.data["results"][0]
        self.assertIn("id", result)
        self.assertIn("menu_item_id", result)
        self.assertIn("branch_id", result)
        self.assertIn("tenant_id", result)
        self.assertIn("favorited_at", result)
        self.assertIn("menu_item", result)
        self.assertIn("name", result["menu_item"])
        self.assertEqual(
            set(result["tenant"].keys()),
            {"id", "name", "slug", "is_active", "status"},
        )
        self.assertEqual(
            set(result["branch"].keys()),
            {"id", "name"},
        )
        self.assertEqual(result["tenant"]["id"], str(self.branch.tenant_id))
        self.assertEqual(result["tenant"]["name"], self.branch.tenant.name)
        self.assertEqual(result["branch"]["id"], str(self.branch.id))
        self.assertEqual(result["branch"]["name"], self.branch.name)

    def test_active_item_is_returned(self):
        response = self.client.get("/api/users/favorites/")
        ids = {item["menu_item_id"] for item in response.data["results"]}
        self.assertIn(str(self.active_item.id), ids)

    def test_inactive_item_is_returned(self):
        response = self.client.get("/api/users/favorites/")
        ids = {item["menu_item_id"] for item in response.data["results"]}
        self.assertIn(str(self.inactive_item.id), ids)

    def test_soft_deleted_item_is_excluded(self):
        response = self.client.get("/api/users/favorites/")
        ids = {item["menu_item_id"] for item in response.data["results"]}
        self.assertNotIn(str(self.soft_deleted_item.id), ids)

    def test_branch_filter(self):
        other_branch = make_branch()
        other_category = make_category(other_branch)
        other_item = make_item(other_branch, other_category)
        Favorite.objects.create(user=self.user, menu_item=other_item)

        response = self.client.get(
            f"/api/users/favorites/?branch_id={self.branch.id}"
        )
        ids = {item["menu_item_id"] for item in response.data["results"]}
        self.assertIn(str(self.active_item.id), ids)
        self.assertNotIn(str(other_item.id), ids)

    def test_anonymous_user_gets_401(self):
        client = APIClient()
        response = client.get("/api/users/favorites/")
        self.assertEqual(response.status_code, 401)


class FavoriteSyncTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)
        Favorite.objects.create(user=self.user, menu_item=self.item)

    def test_sync_returns_version_and_ids(self):
        response = self.client.get("/api/users/favorites/sync/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("sync", response.data)
        self.assertIn("favorite_ids", response.data)
        self.assertEqual(response.data["sync"]["total_count"], 1)
        self.assertEqual(response.data["favorite_ids"], [str(self.item.id)])


class FavoriteCreateTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)

    def test_create_returns_201_with_favorite_and_sync(self):
        response = self.client.post(
            "/api/users/favorites/",
            {"menu_item_id": str(self.item.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created"])
        self.assertIsNotNone(response.data["favorite"])
        self.assertIn("sync", response.data)
        self.assertEqual(response.data["favorite"]["menu_item_id"], str(self.item.id))
        favorite = response.data["favorite"]
        self.assertEqual(favorite["tenant"]["name"], self.branch.tenant.name)
        self.assertEqual(favorite["branch"]["name"], self.branch.name)

    def test_create_is_idempotent(self):
        self.client.post(
            "/api/users/favorites/",
            {"menu_item_id": str(self.item.id)},
            format="json",
        )
        response = self.client.post(
            "/api/users/favorites/",
            {"menu_item_id": str(self.item.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["created"])

    def test_deleted_item_returns_404(self):
        MenuItem.objects.filter(id=self.item.id).update(deleted_at=timezone.now())
        response = self.client.post(
            "/api/users/favorites/",
            {"menu_item_id": str(self.item.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "favorite_menu_item_not_found")

    def test_inactive_item_returns_400(self):
        MenuItem.objects.filter(id=self.item.id).update(is_active=False)
        response = self.client.post(
            "/api/users/favorites/",
            {"menu_item_id": str(self.item.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"]["code"],
            "favorite_menu_item_not_favoritable",
        )


class FavoriteDestroyTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)

    def test_delete_removes_favorite(self):
        Favorite.objects.create(user=self.user, menu_item=self.item)
        response = self.client.delete(f"/api/users/favorites/{self.item.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["removed"])
        self.assertIn("sync", response.data)
        self.assertFalse(
            Favorite.objects.filter(user=self.user, menu_item=self.item).exists()
        )

    def test_delete_is_idempotent(self):
        response = self.client.delete(f"/api/users/favorites/{self.item.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["removed"])


class FavoriteDeprecatedToggleTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.item = make_item(self.branch, self.category)

    def test_deprecated_toggle_adds_and_removes(self):
        response = self.client.post(f"/api/users/favorites/{self.item.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("favorite", response.data)
        self.assertEqual(response["Deprecation"], "true")

        response = self.client.post(f"/api/users/favorites/{self.item.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["removed"])

    def test_anonymous_user_gets_401(self):
        client = APIClient()
        response = client.post(f"/api/users/favorites/{self.item.id}/")
        self.assertEqual(response.status_code, 401)
