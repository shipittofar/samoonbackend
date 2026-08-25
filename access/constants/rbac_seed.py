"""
Single source of truth for RBAC reference data.

Transcribed from frontend/src/services/permission.service.ts
(ALL_PERMISSIONS, ROLE_PERMISSION_MAP, ROLE_TEMPLATES).

Project rule: migrations, tests, and services MUST import from this module.
Never duplicate slug strings elsewhere.
"""

from __future__ import annotations

# Permissions that must never be seeded (RBAC_BACKEND_CONTRACT.md Phase 4).
_EXCLUDED_PERMISSION_SLUGS: frozenset[str] = frozenset({"dashboard:access"})

# ── Canonical permission slugs (ALL_PERMISSIONS minus exclusions) ─────────────

_ALL_PERMISSION_SLUGS: tuple[str, ...] = (
    # Orders
    "orders.view",
    "orders.manage",
    "orders.create",
    "orders.edit",
    "orders.cancel",
    "orders.delete",
    # Menu
    "menu.view",
    "menu.manage",
    # Categories (menu sub-resource — live frontend)
    "category.view",
    "category.create",
    "category.update",
    "category.delete",
    # Extras (menu sub-resource — live frontend)
    "extras.view",
    "extras.create",
    "extras.update",
    "extras.delete",
    # Tags (menu sub-resource — live frontend)
    "tag.view",
    "tag.create",
    "tag.update",
    "tag.delete",
    # Reservations
    "reservations.view",
    "reservations.manage",
    # Customers
    "customers.view",
    "customers.manage",
    "customers.create",
    "customers.edit",
    # Payments
    "payments.process",
    "payments.refund",
    # Tables
    "tables.view",
    "tables.assign",
    # Kitchen
    "kitchen.view",
    "kitchen.manage",
    # Vendors
    "vendors.view",
    "vendors.manage",
    # Promotions
    "promotions.view",
    "promotions.manage",
    # Loyalty
    "loyalty.view",
    "loyalty.manage",
    # Analytics
    "analytics.view",
    "analytics.export",
    # Staff
    "staff.view",
    "staff.manage",
    "staff.create",
    "staff.edit",
    "staff.delete",
    # Branches
    "branches.view",
    "branches.manage",
    "branches.create",
    "branches.update",
    "branches.delete",
    # Settings
    "settings.view",
    "settings.manage",
    "settings.edit",  # legacy slug from access migration 0004 — retained for compatibility
    "featureflags.manage",
    # Tenant
    "tenant.view",
    "tenant.manage",
    # Audit
    "audit.view",
    "audit.export",
    "audit.manage",
    # Notifications
    "notifications.view",
    "notifications.manage",
    "notifications.preferences",
    # Operations
    "operations.view",
    "operations.manage",
    # RBAC platform administration
    "rbac.manage_roles",
)

PERMISSION_SLUGS: frozenset[str] = frozenset(_ALL_PERMISSION_SLUGS)

# ── Permission descriptions (contract Phase 4 + extensions) ───────────────────

_PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "orders.view": "View order list/detail",
    "orders.manage": "Update order status/details",
    "orders.create": "Create a new order (POS)",
    "orders.edit": "Edit an existing order",
    "orders.cancel": "Cancel an order",
    "orders.delete": "Permanently delete an order record",
    "menu.view": "View menu items/categories",
    "menu.manage": "Create/edit/delete menu items",
    "category.view": "View menu categories",
    "category.create": "Create menu categories",
    "category.update": "Update menu categories",
    "category.delete": "Delete menu categories",
    "extras.view": "View menu extras",
    "extras.create": "Create menu extras",
    "extras.update": "Update menu extras",
    "extras.delete": "Delete menu extras",
    "tag.view": "View menu tags",
    "tag.create": "Create menu tags",
    "tag.update": "Update menu tags",
    "tag.delete": "Delete menu tags",
    "reservations.view": "View reservation list",
    "reservations.manage": "Confirm/cancel/edit reservations",
    "customers.view": "View customer profiles",
    "customers.manage": "Edit/merge customer records",
    "customers.create": "Manually create a customer record",
    "customers.edit": "Edit a specific customer's fields",
    "payments.process": "Charge/process a payment",
    "payments.refund": "Issue a refund",
    "tables.view": "View table layout/status",
    "tables.assign": "Assign a table to an order/party",
    "kitchen.view": "View kitchen display / order queue",
    "kitchen.manage": "Update prep status in KDS",
    "vendors.view": "View food-court vendor list",
    "vendors.manage": "Onboard/edit/suspend vendors",
    "promotions.view": "View promotions/happy-hour rules",
    "promotions.manage": "Create/edit promotions",
    "loyalty.view": "View loyalty program state",
    "loyalty.manage": "Edit loyalty rules/rewards",
    "analytics.view": "View analytics dashboards",
    "analytics.export": "Export analytics data (CSV etc.)",
    "staff.view": "View staff roster",
    "staff.manage": "Edit staff roles/assignments",
    "staff.create": "Invite a new staff member",
    "staff.edit": "Edit an existing staff member",
    "staff.delete": "Remove a staff member",
    "branches.view": "View branch/location list",
    "branches.manage": "Create/edit branches",
    "branches.create": "Create branches",
    "branches.update": "Update branches",
    "branches.delete": "Delete branches",
    "settings.view": "View tenant settings",
    "settings.manage": "Edit tenant settings",
    "settings.edit": "Edit tenant settings (legacy slug)",
    "featureflags.manage": "Toggle tenant feature flags",
    "tenant.view": "View tenant ownership/billing info",
    "tenant.manage": "Tenant transfer/archive/suspend",
    "audit.view": "View audit log",
    "audit.export": "Export audit log",
    "audit.manage": "Administer audit retention/settings",
    "notifications.view": "View notification center",
    "notifications.manage": "Send/manage broadcast notifications",
    "notifications.preferences": "Edit own notification preferences",
    "operations.view": "View real-time operations dashboard",
    "operations.manage": "Modify live operational state",
    "rbac.manage_roles": "Create and edit global role definitions and permissions",
}


def _parse_resource_action(slug: str) -> tuple[str, str]:
    if slug == "featureflags.manage":
        return "featureflags", "manage"
    resource, _, action = slug.partition(".")
    return resource, action


def _permission_row(slug: str) -> tuple[str, str, str, str]:
    resource, action = _parse_resource_action(slug)
    description = _PERMISSION_DESCRIPTIONS.get(slug, slug)
    return resource, action, slug, description


# Exported as list of (resource, action, slug, description) for migrations.
PERMISSIONS: tuple[tuple[str, str, str, str], ...] = tuple(
    _permission_row(slug) for slug in _ALL_PERMISSION_SLUGS
)

# ── System roles (ROLE_TEMPLATES) ───────────────────────────────────────────

ROLES: tuple[dict[str, str | bool], ...] = (
    {
        "slug": "owner",
        "name": "Owner",
        "description": "Full platform access including tenant ownership and billing operations.",
        "system_role": True,
    },
    {
        "slug": "admin",
        "name": "Admin",
        "description": "Full operational administration. Cannot perform tenant ownership actions.",
        "system_role": True,
    },
    {
        "slug": "manager",
        "name": "Manager",
        "description": "Restaurant management — floor, staff, schedules, menus, and orders.",
        "system_role": True,
    },
    {
        "slug": "cashier",
        "name": "Cashier",
        "description": "Orders, payments, and POS. No kitchen, analytics, or settings access.",
        "system_role": True,
    },
    {
        "slug": "waiter",
        "name": "Waiter",
        "description": "Tables, orders, and reservations. No settings, analytics, or kitchen.",
        "system_role": True,
    },
    {
        "slug": "kitchen",
        "name": "Kitchen",
        "description": "Kitchen display, order queue, and preparation status only.",
        "system_role": True,
    },
    {
        "slug": "marketing",
        "name": "Marketing",
        "description": "Promotions, loyalty, campaigns, and analytics. No payments or settings.",
        "system_role": True,
    },
    {
        "slug": "support",
        "name": "Support",
        "description": "Read-only customer assistance — customers, reservations, and notifications.",
        "system_role": True,
    },
)

# ── Role → permission slugs (ROLE_PERMISSION_MAP minus dashboard:access) ───────

def _without_dashboard(slugs: frozenset[str]) -> frozenset[str]:
    return frozenset(s for s in slugs if s not in _EXCLUDED_PERMISSION_SLUGS)


_ALL: frozenset[str] = PERMISSION_SLUGS

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": _without_dashboard(_ALL - frozenset({"rbac.manage_roles"})),
    "admin": _without_dashboard(_ALL - frozenset({"tenant.view", "tenant.manage"})),
    "manager": _without_dashboard(
        frozenset(
            {
                "orders.view",
                "orders.manage",
                "orders.create",
                "orders.edit",
                "orders.cancel",
                "menu.view",
                "menu.manage",
                "category.view",
                "category.create",
                "category.update",
                "category.delete",
                "extras.view",
                "extras.create",
                "extras.update",
                "extras.delete",
                "tag.view",
                "tag.create",
                "tag.update",
                "tag.delete",
                "reservations.view",
                "reservations.manage",
                "customers.view",
                "customers.manage",
                "customers.create",
                "customers.edit",
                "payments.process",
                "tables.view",
                "tables.assign",
                "staff.view",
                "staff.manage",
                "staff.create",
                "staff.edit",
                "staff.delete",
                "branches.view",
                "notifications.view",
                "operations.view",
            }
        )
    ),
    "cashier": _without_dashboard(
        frozenset(
            {
                "orders.view",
                "orders.manage",
                "orders.create",
                "orders.cancel",
                "customers.view",
                "payments.process",
                "payments.refund",
                "tables.view",
                "tables.assign",
                "notifications.view",
                "operations.view",
            }
        )
    ),
    "waiter": _without_dashboard(
        frozenset(
            {
                "orders.view",
                "orders.manage",
                "orders.create",
                "orders.edit",
                "menu.view",
                "category.view",
                "extras.view",
                "tag.view",
                "reservations.view",
                "reservations.manage",
                "customers.view",
                "payments.process",
                "tables.view",
                "tables.assign",
                "notifications.view",
                "notifications.preferences",
                "operations.view",
            }
        )
    ),
    "kitchen": _without_dashboard(
        frozenset(
            {
                "orders.view",
                "kitchen.view",
                "kitchen.manage",
                "operations.view",
                "notifications.view",
            }
        )
    ),
    "marketing": _without_dashboard(
        frozenset(
            {
                "analytics.view",
                "analytics.export",
                "customers.view",
                "promotions.view",
                "promotions.manage",
                "loyalty.view",
                "loyalty.manage",
                "notifications.view",
            }
        )
    ),
    "support": _without_dashboard(
        frozenset(
            {
                "customers.view",
                "reservations.view",
                "branches.view",
                "notifications.view",
            }
        )
    ),
}

# Validate seed integrity at import time.
assert set(ROLE_PERMISSIONS) == {role["slug"] for role in ROLES}
for _role_slug, _perms in ROLE_PERMISSIONS.items():
    unknown = _perms - PERMISSION_SLUGS
    assert not unknown, f"Role {_role_slug} references unknown permissions: {unknown}"
