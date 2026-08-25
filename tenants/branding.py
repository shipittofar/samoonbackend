"""Shared tenant branding read projection and write validation.

Colors and fonts are stored in ``Tenant.settings.theme``.
Tenant logos use ``Tenant.image`` only — never ``settings.theme.logo*``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tenants.dto import _image_url

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
FONT_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

MAX_FONT_BODY_LENGTH = 64
MAX_LOCALE_KEY_LENGTH = 10
MAX_FONTS_BY_LOCALE_ENTRIES = 10

PROHIBITED_THEME_KEYS = frozenset({"logoUrl", "logo"})

CANONICAL_BRANDING_KEYS = (
    "primaryColor",
    "accentHoverColor",
    "fontBody",
    "fontsByLocale",
)


@dataclass(slots=True)
class TenantBranding:
    primaryColor: str | None = None
    accentHoverColor: str | None = None
    fontBody: str | None = None
    fontsByLocale: dict[str, str] = field(default_factory=dict)


def _theme_dict(tenant) -> dict:
    settings = getattr(tenant, "settings", None) or {}
    if not isinstance(settings, dict):
        return {}
    theme = settings.get("theme") or {}
    if not isinstance(theme, dict):
        return {}
    return theme


def build_tenant_branding(tenant) -> TenantBranding:
    """Project canonical branding fields from ``tenant.settings.theme``."""
    theme = _theme_dict(tenant)
    branding = TenantBranding()

    if "primaryColor" in theme:
        branding.primaryColor = theme["primaryColor"]
    if "accentHoverColor" in theme:
        branding.accentHoverColor = theme["accentHoverColor"]
    if "fontBody" in theme:
        branding.fontBody = theme["fontBody"]
    if "fontsByLocale" in theme and isinstance(theme["fontsByLocale"], dict):
        branding.fontsByLocale = dict(theme["fontsByLocale"])

    return branding


def build_legacy_discover_theme(branding: TenantBranding) -> dict:
    """Backward-compatible discover ``theme`` shim (``primaryColor`` only)."""
    if branding.primaryColor is None:
        return {}
    return {"primaryColor": branding.primaryColor}


def resolve_tenant_image_url(tenant) -> str | None:
    """Resolve tenant logo URL from ``image_url`` (DTO) or ``image`` (ORM)."""
    url = getattr(tenant, "image_url", None)
    if url:
        return url
    image = getattr(tenant, "image", None)
    if not image:
        return None
    return _image_url(image)


def _reject_css_injection(value: str, field_name: str) -> None:
    if any(char in value for char in ";{}\"'"):
        raise ValueError(f"{field_name} contains invalid characters.")
    if "url(" in value.lower():
        raise ValueError(f"{field_name} contains invalid characters.")


def _validate_color(value, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if not HEX_COLOR_RE.match(value):
        raise ValueError(f"{field_name} must be a hex color (#RRGGBB).")


def _validate_font_token(value, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string.")
    if len(value) > MAX_FONT_BODY_LENGTH:
        raise ValueError(f"{field_name} must be at most {MAX_FONT_BODY_LENGTH} characters.")
    _reject_css_injection(value, field_name)
    if not FONT_TOKEN_RE.match(value):
        raise ValueError(f"{field_name} must be a lowercase alphanumeric token.")


def validate_tenant_branding(theme) -> None:
    """Validate ``settings.theme`` on tenant create/update."""
    if theme is None:
        return
    if not isinstance(theme, dict):
        raise ValueError("theme must be a JSON object.")

    for prohibited in PROHIBITED_THEME_KEYS:
        if prohibited in theme:
            raise ValueError(
                "theme.logoUrl is not supported. "
                "Upload the tenant logo using the image field instead."
            )

    if "primaryColor" in theme:
        _validate_color(theme["primaryColor"], "primaryColor")
    if "accentHoverColor" in theme:
        _validate_color(theme["accentHoverColor"], "accentHoverColor")
    if "fontBody" in theme:
        _validate_font_token(theme["fontBody"], "fontBody")

    if "fontsByLocale" in theme:
        fonts_by_locale = theme["fontsByLocale"]
        if not isinstance(fonts_by_locale, dict):
            raise ValueError("fontsByLocale must be a JSON object.")
        if len(fonts_by_locale) > MAX_FONTS_BY_LOCALE_ENTRIES:
            raise ValueError(
                f"fontsByLocale must contain at most {MAX_FONTS_BY_LOCALE_ENTRIES} entries."
            )
        for locale_key, font_id in fonts_by_locale.items():
            if not isinstance(locale_key, str) or not locale_key:
                raise ValueError("fontsByLocale keys must be non-empty strings.")
            if len(locale_key) > MAX_LOCALE_KEY_LENGTH:
                raise ValueError(
                    f"fontsByLocale locale keys must be at most {MAX_LOCALE_KEY_LENGTH} characters."
                )
            _validate_font_token(font_id, f"fontsByLocale[{locale_key!r}]")
