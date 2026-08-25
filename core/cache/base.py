from django.core.cache import cache


def cache_get(key: str):
    return cache.get(key)


def cache_set(key: str, value, ttl: int) -> None:
    cache.set(key, value, ttl)


def cache_delete(key: str) -> None:
    cache.delete(key)