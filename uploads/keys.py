from __future__ import annotations

import re
import uuid


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    ext = filename.rsplit(".", 1)[-1].lower()
    ext = _UNSAFE_CHARS.sub("", ext)
    if not ext or "/" in ext or "\\" in ext or ".." in ext:
        return ""
    return ext[:12]


def safe_original_filename(filename: str | None) -> str:
    if not filename:
        return "upload"
    name = filename.replace("\\", "/").split("/")[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip("._")
    return (name or "upload")[:180]


def original_storage_key(*, tenant_id, asset_id: uuid.UUID, user_id=None) -> str:
    if tenant_id:
        return f"tenants/{tenant_id}/assets/{asset_id}/original"
    return f"users/{user_id}/assets/{asset_id}/original"


def variant_storage_key(original_key: str, variant: str) -> str:
    prefix = original_key.rsplit("/", 1)[0]
    return f"{prefix}/variants/{variant}.webp"
