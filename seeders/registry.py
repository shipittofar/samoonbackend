class SeedRegistry:
    def __init__(self):
        self._store: dict[str, object] = {}

    def register(self, key: str, instance):
        self._store[key] = instance
        return instance

    def get(self, key: str):
        try:
            return self._store[key]
        except KeyError:
            raise KeyError(
                f"Seed key '{key}' not found. "
                f"Did the seeder that registers it run before this one?"
            )

    def append(self, list_key: str, instance):
        """Add an instance to a named list (for one-to-many seed relations)."""
        self._store.setdefault(list_key, []).append(instance)
        return instance

    def get_list(self, list_key: str) -> list:
        return self._store.get(list_key, [])