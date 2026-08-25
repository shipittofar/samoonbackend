"""Catalog cache key versioning — single source of truth for runtime + migrations."""
from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from access.constants.rbac_cache import (
    CATALOG_CACHE_VERSION,
    PERMISSIONS_CATALOG_CACHE_KEY,
    ROLES_CATALOG_CACHE_KEY,
    bust_rbac_catalog_caches,
)
from access.services import rbac_bll as rbac_bll_module
from access.services.rbac_bll import rbac_bll


class CatalogCacheKeyContractTests(SimpleTestCase):
    def test_runtime_keys_come_from_shared_constant(self):
        self.assertEqual(
            rbac_bll_module.PERMISSIONS_CATALOG_CACHE_KEY,
            PERMISSIONS_CATALOG_CACHE_KEY,
        )
        self.assertEqual(
            rbac_bll_module.ROLES_CATALOG_CACHE_KEY,
            ROLES_CATALOG_CACHE_KEY,
        )
        self.assertEqual(
            PERMISSIONS_CATALOG_CACHE_KEY,
            f"rbac:permissions:catalog:{CATALOG_CACHE_VERSION}",
        )
        self.assertEqual(
            ROLES_CATALOG_CACHE_KEY,
            f"rbac:roles:catalog:{CATALOG_CACHE_VERSION}",
        )

    def test_migrations_import_shared_bust_helper(self):
        import importlib
        import inspect

        for module_name in (
            "access.migrations.0005_seed_rbac_reference_data",
            "access.migrations.0015_seed_rbac_manage_roles_permission",
        ):
            module = importlib.import_module(module_name)
            source = inspect.getsource(module)
            self.assertIn("bust_rbac_catalog_caches", source)
            self.assertNotIn('"rbac:permissions:catalog:v1"', source)
            self.assertNotIn('"rbac:roles:catalog:v1"', source)
            self.assertNotIn("cache.delete(", source)


class CatalogCacheBustTests(TestCase):
    def test_bust_clears_current_runtime_catalog_keys(self):
        cache.set(PERMISSIONS_CATALOG_CACHE_KEY, ["stale-perms"], timeout=60)
        cache.set(ROLES_CATALOG_CACHE_KEY, ["stale-roles"], timeout=60)
        # Legacy literals must not be the keys runtime uses.
        cache.set("rbac:permissions:catalog:v1", ["legacy"], timeout=60)
        cache.set("rbac:roles:catalog:v1", ["legacy"], timeout=60)

        bust_rbac_catalog_caches()

        self.assertIsNone(cache.get(PERMISSIONS_CATALOG_CACHE_KEY))
        self.assertIsNone(cache.get(ROLES_CATALOG_CACHE_KEY))
        # Legacy keys are intentionally left alone — VERSION bump orphans them.
        self.assertEqual(cache.get("rbac:permissions:catalog:v1"), ["legacy"])
        self.assertEqual(cache.get("rbac:roles:catalog:v1"), ["legacy"])

    def test_invalidate_reference_caches_targets_same_keys(self):
        cache.set(PERMISSIONS_CATALOG_CACHE_KEY, ["cached"], timeout=60)
        cache.set(ROLES_CATALOG_CACHE_KEY, ["cached"], timeout=60)

        rbac_bll.invalidate_reference_caches()

        self.assertIsNone(cache.get(PERMISSIONS_CATALOG_CACHE_KEY))
        self.assertIsNone(cache.get(ROLES_CATALOG_CACHE_KEY))
