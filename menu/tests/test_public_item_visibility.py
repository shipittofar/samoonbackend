"""Truth-table tests for public menu visibility (is_active vs available)."""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from core.cache import cache_delete, CacheKeys
from menu.models import MenuCategory, MenuItem
from menu.selectors.menu_dal import MenuDataAccessLayer
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


def make_item(branch, category, *, name, is_active=True, available=True):
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name=name,
        price=Decimal("9.99"),
        is_active=is_active,
        available=available,
    )


class PublicItemVisibilityTruthTableTests(TestCase):
    """Cases 1–5 from the public visibility specification."""

    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.category = make_category(self.branch)
        self.active_available = make_item(
            self.branch,
            self.category,
            name="Active Available",
            is_active=True,
            available=True,
        )
        self.active_unavailable = make_item(
            self.branch,
            self.category,
            name="Active Unavailable",
            is_active=True,
            available=False,
        )
        self.inactive_available = make_item(
            self.branch,
            self.category,
            name="Inactive Available",
            is_active=False,
            available=True,
        )
        self.inactive_unavailable = make_item(
            self.branch,
            self.category,
            name="Inactive Unavailable",
            is_active=False,
            available=False,
        )
        MenuDataAccessLayer.invalidate_branch_items_cache(self.branch.id)

    def _names_from_branch_path(self, *, query=""):
        url = f"/api/menu/items/branches/{self.branch.id}/"
        if query:
            url = f"{url}?{query}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        return {item["name"] for item in response.data["results"]}

    def _names_from_items_alias(self, *, extra_params=None):
        params = {"branch_id": str(self.branch.id)}
        if extra_params:
            params.update(extra_params)
        response = self.client.get("/api/menu/items/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return {item["name"] for item in response.data["results"]}

    def test_case_1_active_available_is_returned(self):
        names = self._names_from_branch_path()
        self.assertIn(self.active_available.name, names)

    def test_case_2_active_unavailable_is_returned(self):
        names = self._names_from_branch_path()
        self.assertIn(self.active_unavailable.name, names)

    def test_case_3_inactive_available_is_hidden(self):
        names = self._names_from_branch_path()
        self.assertNotIn(self.inactive_available.name, names)

    def test_case_4_inactive_unavailable_is_hidden(self):
        names = self._names_from_branch_path()
        self.assertNotIn(self.inactive_unavailable.name, names)

    def test_case_5_payload_exposes_independent_fields(self):
        response = self.client.get(
            f"/api/menu/items/branches/{self.branch.id}/",
        )
        self.assertEqual(response.status_code, 200, response.data)
        by_name = {item["name"]: item for item in response.data["results"]}
        item = by_name[self.active_unavailable.name]
        self.assertTrue(item["is_active"])
        self.assertFalse(item["available"])

    def test_items_alias_with_sort_popular_includes_active_unavailable(self):
        names = self._names_from_items_alias(
            extra_params={"sort": "popular"},
        )
        self.assertIn(self.active_unavailable.name, names)
        self.assertNotIn(self.inactive_available.name, names)

    def test_available_true_query_param_is_optional_ordering_filter(self):
        names = self._names_from_branch_path(query="available=true")
        self.assertIn(self.active_available.name, names)
        self.assertNotIn(self.active_unavailable.name, names)

    def test_empty_available_query_param_does_not_filter_visibility(self):
        names = self._names_from_branch_path(query="available=")
        self.assertIn(self.active_available.name, names)
        self.assertIn(self.active_unavailable.name, names)

    def test_stale_branch_cache_does_not_hide_active_unavailable_items(self):
        """Simulate stale cached rows with is_active=False after DB fix."""
        stale_items = list(
            MenuItem.objects.filter(branch_id=self.branch.id).prefetch_related(
                "tags",
                "item_extras__extra",
                "item_extra_groups",
                "category",
            )
        )
        for item in stale_items:
            if item.name == self.active_unavailable.name:
                item.is_active = False

        from core.cache import cache_set
        from core.cache import CacheTTL

        cache_set(
            CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=self.branch.id),
            stale_items,
            CacheTTL.MENU_BRANCH_ITEMS_ALL,
        )

        names = self._names_from_branch_path()
        self.assertIn(self.active_unavailable.name, names)

        cache_delete(
            CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=self.branch.id)
        )
