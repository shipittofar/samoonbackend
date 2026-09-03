from uuid import UUID


def console_group_name(*, tenant_id: UUID | str, branch_id: UUID | str) -> str:
    """Deterministic Channels group isolated by tenant and branch.

    InMemoryChannelLayer (and Channels' group name validator) only allow
    ASCII alphanumerics, hyphens, underscores, and periods — no colons.
    """
    return f"console.{tenant_id}.{branch_id}"
