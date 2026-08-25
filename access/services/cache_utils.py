from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)


def safe_cache_get(key, default=None):
    try:
        return cache.get(key, default)
    except Exception:
        logger.warning("Cache get failed for key %s", key, exc_info=True)
        return default


def safe_cache_set(key, value, timeout=None) -> None:
    try:
        cache.set(key, value, timeout)
    except Exception:
        logger.warning("Cache set failed for key %s", key, exc_info=True)


def safe_cache_delete(key) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("Cache delete failed for key %s", key, exc_info=True)
