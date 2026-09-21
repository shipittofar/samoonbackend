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


def _safe_id(value) -> str:
    text = str(value or "")
    if not text or ".." in text or "/" in text or "\\" in text:
        raise ValueError("Unsafe identifier for storage key.")
    return text


def assert_safe_storage_key(key: str) -> str:
    if not key or ".." in key or key.startswith("/") or "\\" in key:
        raise ValueError("Unsafe storage key.")
    if not (key.startswith("tenants/") or key.startswith("users/")):
        raise ValueError("Unsafe storage key.")
    return key


def original_storage_key(*, tenant_id, asset_id: uuid.UUID, user_id=None) -> str:
    asset_part = _safe_id(asset_id)
    if tenant_id:
        return f"tenants/{_safe_id(tenant_id)}/assets/{asset_part}/original"
    return f"users/{_safe_id(user_id)}/assets/{asset_part}/original"


def variant_storage_key(original_key: str, variant: str) -> str:
    assert_safe_storage_key(original_key)
    if variant not in {"thumbnail", "medium", "optimized"}:
        raise ValueError("Unknown image variant.")
    prefix = original_key.rsplit("/", 1)[0]
    return f"{prefix}/variants/{variant}.webp"
