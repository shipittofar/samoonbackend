"""Seeder cache-bust coverage — bulk invalidation after seed writes."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from access.tests.helpers import make_branch, make_tenant
from core.cache import CacheKeys
from menu.models import MenuCategory, MenuItem
from seeders.cache_bust import bust_caches_after_seed
from seeders.registry import SeedRegistry
from tenants.models import Tenant
from tenants.selectors.tenant_dal import (
    BranchDataAccessLayer,
    TenantDataAccessLayer,
)


class SeedCacheBustTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner_user, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="Seed Branch")
        self.category = MenuCategory.objects.create(
            branch=self.branch,
            name="Mains",
            sort_order=0,
        )
        self.item = MenuItem.objects.create(
            branch=self.branch,
            category=self.category,
            name="Burger",
            price=Decimal("10000"),
            is_active=True,
            available=True,
        )

    def tearDown(self):
        cache.clear()

    def _registry(self) -> SeedRegistry:
        registry = SeedRegistry()
        registry.append("tenants", self.tenant)
        registry.append("branches", self.branch)
        registry.append(f"categories:{self.branch.pk}", self.category)
        registry.append(f"items:{self.branch.pk}", self.item)
        return registry

    def test_bust_refreshes_stale_tenant_detail_cache(self):
        TenantDataAccessLayer._refresh_tenant_detail_cache(self.tenant.id)
        key = CacheKeys.TENANT_DETAIL.format(tenant_id=self.tenant.id)
        self.assertIsNotNone(cache.get(key))

        Tenant.objects.filter(pk=self.tenant.id).update(name="Post-Seed Name")
        # Stale DTO payload still present until bust.
        stale = cache.get(key)
        self.assertEqual(stale["name"], self.tenant.name)

        bust_caches_after_seed(self._registry())

        cached = TenantDataAccessLayer.get_tenant_by_id(self.tenant.id)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.name, "Post-Seed Name")

    def test_bust_refreshes_branch_and_menu_aggregate_caches(self):
        BranchDataAccessLayer._refresh_branch_detail_cache(
            self.branch.id, self.tenant.id
        )
        branch_key = CacheKeys.BRANCH_DETAIL.format(
            tenant_id=self.tenant.id, branch_id=self.branch.id
        )
        items_key = CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=self.branch.id)
        cache.set(items_key, ["stale-sentinel"], timeout=60)
        self.assertEqual(cache.get(items_key), ["stale-sentinel"])

        bust_caches_after_seed(self._registry())

        self.assertIsNotNone(cache.get(branch_key))
        refreshed_items = cache.get(items_key)
        self.assertNotEqual(refreshed_items, ["stale-sentinel"])
        # Menu aggregate cache still stores model instances today; accept either
        # ORM rows or DTO-shaped payloads with an ``id`` attribute.
        self.assertTrue(
            any(getattr(item, "id", None) == self.item.id for item in refreshed_items)
        )

    def test_bust_invokes_central_invalidate_helpers(self):
        registry = self._registry()
        with patch.object(
            TenantDataAccessLayer, "invalidate_tenant_cache"
        ) as inv_tenant, patch.object(
            BranchDataAccessLayer, "invalidate_branch_cache"
        ) as inv_branch:
            bust_caches_after_seed(registry)

        inv_tenant.assert_called_once_with(self.tenant.id, self.owner_user.id)
        inv_branch.assert_called_once_with(self.tenant.id, self.branch.id)
