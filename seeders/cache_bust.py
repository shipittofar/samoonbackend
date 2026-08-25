"""
Bulk cache invalidation after seeding / management-command bulk writes.

Uses the same ``invalidate_*`` helpers as API/BLL paths — never calls
``cache.delete`` directly. Prefer this over per-row invalidation when a
command touches many cached entities.
"""
from __future__ import annotations

from seeders.registry import SeedRegistry


def bust_caches_after_seed(registry: SeedRegistry) -> None:
    """
    Refresh tenant/branch/menu caches for every entity registered during seed.

    Safe to call with a partial registry (``--only``) — missing lists are no-ops.
    """
    from menu.selectors.category_dal import CategoryDataAccessLayer
    from menu.selectors.extra_group_dal import ExtraGroupDataAccessLayer
    from menu.selectors.item_dal import ExtraDataAccessLayer, ItemDataAccessLayer
    from menu.selectors.menu_dal import MenuDataAccessLayer
    from menu.selectors.tag_dal import TagDataAccessLayer
    from tenants.selectors.tenant_dal import (
        BranchDataAccessLayer,
        TenantDataAccessLayer,
    )

    for tenant in registry.get_list("tenants"):
        owner = getattr(tenant, "owner", None)
        owner_user_id = getattr(owner, "user_id", None)
        TenantDataAccessLayer.invalidate_tenant_cache(tenant.id, owner_user_id)

    for branch in registry.get_list("branches"):
        tenant_id = branch.tenant_id
        branch_id = branch.id
        BranchDataAccessLayer.invalidate_branch_cache(tenant_id, branch_id)

        TagDataAccessLayer.invalidate_tag_cache(branch_id)
        CategoryDataAccessLayer.invalidate_category_cache(branch_id)
        ExtraDataAccessLayer.invalidate_extra_cache(branch_id)
        ExtraGroupDataAccessLayer.invalidate_extra_group_cache(branch_id)

        for category in registry.get_list(f"categories:{branch.pk}"):
            ItemDataAccessLayer.invalidate_item_cache(branch_id, category.id)

        for item in registry.get_list(f"items:{branch.pk}"):
            ItemDataAccessLayer.invalidate_item_cache(
                branch_id, item.category_id, item.id
            )

        # Ensure branch aggregates are current even when no categories/items
        # were registered (e.g. ``--only branch``).
        MenuDataAccessLayer.invalidate_branch_items_cache(branch_id)
        MenuDataAccessLayer.invalidate_categories_with_items_cache(branch_id)
