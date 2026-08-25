"""
Single source of truth for RBAC reference-catalog cache keys.

Runtime code (``rbac_bll``) and seed migrations must import these symbols —
never hardcode ``rbac:permissions:catalog:v…`` / ``rbac:roles:catalog:v…``
literals elsewhere. Bump ``CATALOG_CACHE_VERSION`` when the seeded catalog
shape or contents change so both catalogs are invalidated together.
"""
from __future__ import annotations

CATALOG_CACHE_VERSION = "v2"

PERMISSIONS_CATALOG_CACHE_KEY = (
    f"rbac:permissions:catalog:{CATALOG_CACHE_VERSION}"
)
ROLES_CATALOG_CACHE_KEY = f"rbac:roles:catalog:{CATALOG_CACHE_VERSION}"


def bust_rbac_catalog_caches() -> None:
    """
    Delete the *current* permission/role catalog keys.

    Used by seed migrations so deploys pick up reference data immediately.
    Prefer ``rbac_bll.invalidate_reference_caches()`` from application code
    (logged/safe deletes).
    """
    from django.core.cache import cache

    cache.delete(PERMISSIONS_CATALOG_CACHE_KEY)
    cache.delete(ROLES_CATALOG_CACHE_KEY)
