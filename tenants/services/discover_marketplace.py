from __future__ import annotations

from tenants.services.branch_availability import is_branch_open

MARKETPLACE_COMPUTED_FIELDS = frozenset({
    "branches",
    "branchCount",
    "openNow",
    "primaryBranchSlug",
})

# Branch-owned fields — not stored on tenant marketplace metadata.
# Discover overlays city/email/phone/description/coverImage from the
# primary public branch so stale settings cannot win.
MARKETPLACE_BRANCH_OWNED_FIELDS = frozenset({
    "cuisines",
    "amenities",
    "city",
    "email",
    "phone_number",
    "description",
    "coverImage",
})


def get_public_branches(tenant) -> list:
    """Return nested public branches from a Tenant model or TenantDiscoverDTO."""
    branches = getattr(tenant, "branches", None)
    if branches is None:
        return []
    if isinstance(branches, list):
        return list(branches)
    return list(branches.all())


def resolve_primary_branch(branches: list):
    if not branches:
        return None

    default_branch = next(
        (branch for branch in branches if getattr(branch, "is_default", False)),
        None,
    )
    if default_branch is not None:
        return default_branch

    return branches[0]


def resolve_primary_branch_slug(branches: list) -> str | None:
    primary = resolve_primary_branch(branches)
    if primary is None:
        return None
    return primary.slug


def _apply_primary_branch_listing_fields(marketplace: dict, branches: list) -> None:
    primary = resolve_primary_branch(branches)
    if primary is None:
        return

    marketplace["city"] = getattr(primary, "city", "") or ""
    marketplace["email"] = getattr(primary, "email", "") or ""
    marketplace["phone_number"] = getattr(primary, "phone", "") or ""
    marketplace["description"] = getattr(primary, "description", "") or ""
    marketplace["coverImage"] = getattr(primary, "cover_image_url", None)


def build_marketplace_metadata(
    tenant,
    branches: list,
) -> dict:
    stored = (getattr(tenant, "settings", None) or {}).get("marketplace") or {}
    # Defense in depth: these keys are stripped on Tenant.save / API write,
    # but QuerySet.update (and pre-migration rows) may still contain them.
    marketplace = {
        key: value
        for key, value in stored.items()
        if key not in MARKETPLACE_COMPUTED_FIELDS
        and key not in MARKETPLACE_BRANCH_OWNED_FIELDS
    }

    _apply_primary_branch_listing_fields(marketplace, branches)

    marketplace["branchCount"] = len(branches)
    marketplace["openNow"] = any(is_branch_open(branch) for branch in branches)

    primary_branch_slug = resolve_primary_branch_slug(branches)
    if primary_branch_slug is not None:
        marketplace["primaryBranchSlug"] = primary_branch_slug

    return marketplace
