from __future__ import annotations

from tenants.services.branch_availability import is_branch_open

MARKETPLACE_COMPUTED_FIELDS = frozenset({
    "branches",
    "branchCount",
    "openNow",
    "primaryBranchSlug",
})

# Branch-owned fields — no longer surfaced on tenant marketplace metadata.
MARKETPLACE_BRANCH_OWNED_FIELDS = frozenset({
    "cuisines",
    "amenities",
})


def get_public_branches(tenant) -> list:
    """Return nested public branches from a Tenant model or TenantDiscoverDTO."""
    branches = getattr(tenant, "branches", None)
    if branches is None:
        return []
    if isinstance(branches, list):
        return list(branches)
    return list(branches.all())


def resolve_primary_branch_slug(branches: list) -> str | None:
    if not branches:
        return None

    default_branch = next(
        (branch for branch in branches if getattr(branch, "is_default", False)),
        None,
    )
    if default_branch is not None:
        return default_branch.slug

    return branches[0].slug


def build_marketplace_metadata(
    tenant,
    branches: list,
) -> dict:
    stored = (getattr(tenant, "settings", None) or {}).get("marketplace") or {}
    marketplace = {
        key: value
        for key, value in stored.items()
        if key not in MARKETPLACE_COMPUTED_FIELDS
        and key not in MARKETPLACE_BRANCH_OWNED_FIELDS
    }

    marketplace["branchCount"] = len(branches)
    marketplace["openNow"] = any(is_branch_open(branch) for branch in branches)

    primary_branch_slug = resolve_primary_branch_slug(branches)
    if primary_branch_slug is not None:
        marketplace["primaryBranchSlug"] = primary_branch_slug

    return marketplace
