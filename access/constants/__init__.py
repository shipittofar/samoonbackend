class MembershipStatus:
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class SystemRoleSlug:
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    CASHIER = "cashier"
    WAITER = "waiter"
    KITCHEN = "kitchen"
    MARKETING = "marketing"
    SUPPORT = "support"


from access.constants.rbac_seed import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
)
from access.constants.rbac_cache import (
    CATALOG_CACHE_VERSION,
    PERMISSIONS_CATALOG_CACHE_KEY,
    ROLES_CATALOG_CACHE_KEY,
    bust_rbac_catalog_caches,
)

__all__ = [
    "MembershipStatus",
    "SystemRoleSlug",
    "PERMISSIONS",
    "ROLE_PERMISSIONS",
    "ROLES",
    "CATALOG_CACHE_VERSION",
    "PERMISSIONS_CATALOG_CACHE_KEY",
    "ROLES_CATALOG_CACHE_KEY",
    "bust_rbac_catalog_caches",
]
