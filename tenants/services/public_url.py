"""Central public URL construction for storefront and QR destinations.

Destination paths are not stored on QR rows. Callers pass the current
tenant/branch slugs so slug changes keep printed QR codes valid.
"""
from __future__ import annotations

from django.conf import settings


QR_RESOLVE_PATH = "/qr/{code}"


def public_site_url() -> str:
    return str(getattr(settings, "PUBLIC_SITE_URL", "") or "").rstrip("/")


def tenant_public_path(tenant_slug: str) -> str:
    return f"/{tenant_slug}"


def branch_public_path(tenant_slug: str, branch_slug: str) -> str:
    return f"/{tenant_slug}/{branch_slug}"


def branch_menu_public_path(tenant_slug: str, branch_slug: str) -> str:
    return f"/{tenant_slug}/{branch_slug}/menu"


def branch_reservation_public_path(tenant_slug: str, branch_slug: str) -> str:
    return f"/{tenant_slug}/{branch_slug}/reservation"


def absolute_public_url(path: str) -> str:
    base = public_site_url()
    if not path.startswith("/"):
        path = f"/{path}"
    if not base:
        return path
    return f"{base}{path}"


def qr_resolve_path(code: str) -> str:
    return QR_RESOLVE_PATH.format(code=code)


def qr_resolve_url(code: str, request=None) -> str:
    path = qr_resolve_path(code)
    if request is not None:
        return request.build_absolute_uri(path)
    api_base = str(getattr(settings, "PUBLIC_API_URL", "") or "").rstrip("/")
    if api_base:
        return f"{api_base}{path}"
    return path


def destination_path(
    destination_type: str,
    *,
    tenant_slug: str,
    branch_slug: str | None = None,
) -> str:
    if destination_type == "tenant":
        return tenant_public_path(tenant_slug)
    if not branch_slug:
        return tenant_public_path(tenant_slug)
    if destination_type == "menu":
        return branch_menu_public_path(tenant_slug, branch_slug)
    if destination_type == "reservation":
        return branch_reservation_public_path(tenant_slug, branch_slug)
    return branch_public_path(tenant_slug, branch_slug)


def qr_payload(code: str, request=None) -> dict:
    return {
        "code": code,
        "url": qr_resolve_url(code, request),
    }
