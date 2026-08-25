from __future__ import annotations

import copy
from datetime import datetime, timezone

from website_builder.constants import DEFAULT_LAYOUT
from website_builder.models import BranchWebsiteOverride, WebsiteLayout, WebsiteLayoutStatus


def _format_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_layout_response(layout: WebsiteLayout) -> dict:
    data = copy.deepcopy(layout.layout_data) if layout.layout_data else {}
    data["status"] = layout.status
    last_saved_at = _format_iso(layout.last_saved_at)
    if last_saved_at:
        data["lastSavedAt"] = last_saved_at
    last_published_at = _format_iso(layout.last_published_at)
    if last_published_at:
        data["lastPublishedAt"] = last_published_at
    return data


_PUBLIC_LAYOUT_KEYS = (
    "hero",
    "about",
    "contact",
    "faq",
    "brandTheme",
    "heroConfig",
    "sectionTemplates",
    "navItems",
)

_INTERNAL_LAYOUT_KEYS = {
    "sections",
    "theme",
    "status",
    "lastSavedAt",
    "lastPublishedAt",
    "publishedVersion",
    "versions",
}


def build_default_public_website_response() -> dict:
    return build_public_website_response_from_layout_data(copy.deepcopy(DEFAULT_LAYOUT))


def build_public_website_response_from_layout_data(layout_data: dict) -> dict:
    data = copy.deepcopy(layout_data) if layout_data else {}
    layout_payload = {key: copy.deepcopy(data[key]) for key in _PUBLIC_LAYOUT_KEYS if key in data}
    return {
        "layout": layout_payload,
        "theme": copy.deepcopy(data.get("theme", DEFAULT_LAYOUT["theme"])),
        "sections": copy.deepcopy(data.get("sections", DEFAULT_LAYOUT["sections"])),
        "branchOverrides": {},
    }


def build_public_website_response(
    *,
    layout: WebsiteLayout,
    branch_overrides: dict[str, dict] | None = None,
) -> dict:
    if layout.status != WebsiteLayoutStatus.PUBLISHED:
        return build_default_public_website_response()

    published_data = build_layout_response(layout)
    response = build_public_website_response_from_layout_data(published_data)
    response["branchOverrides"] = copy.deepcopy(branch_overrides or {})
    return response


class WebsiteBuilderDataAccessLayer:
    @staticmethod
    def get_layout_for_tenant(*, tenant_id) -> WebsiteLayout | None:
        return (
            WebsiteLayout.objects.select_related("tenant")
            .filter(tenant_id=tenant_id)
            .first()
        )

    @staticmethod
    def create_default_layout(*, tenant) -> WebsiteLayout:
        return WebsiteLayout.objects.create(
            tenant=tenant,
            layout_data=copy.deepcopy(DEFAULT_LAYOUT),
            status=WebsiteLayoutStatus.DRAFT,
        )

    @staticmethod
    def save_layout(*, layout: WebsiteLayout, layout_data: dict, saved_at: datetime) -> WebsiteLayout:
        layout.layout_data = copy.deepcopy(layout_data)
        layout.status = layout_data.get("status", layout.status)
        layout.last_saved_at = saved_at
        layout.save(
            update_fields=["layout_data", "status", "last_saved_at", "updated_at"]
        )
        return layout

    @staticmethod
    def get_all_branch_overrides(*, layout: WebsiteLayout) -> dict[str, dict]:
        overrides = BranchWebsiteOverride.objects.filter(website_layout=layout).select_related("branch")
        return {
            str(override.branch_id): copy.deepcopy(override.override_data or {})
            for override in overrides
        }

    @staticmethod
    def get_branch_override(
        *, layout: WebsiteLayout, branch_id
    ) -> BranchWebsiteOverride | None:
        return (
            BranchWebsiteOverride.objects.filter(
                website_layout=layout,
                branch_id=branch_id,
            )
            .first()
        )

    @staticmethod
    def save_branch_override(
        *, layout: WebsiteLayout, branch, override_data: dict
    ) -> BranchWebsiteOverride:
        override, _created = BranchWebsiteOverride.objects.update_or_create(
            website_layout=layout,
            branch=branch,
            defaults={"override_data": copy.deepcopy(override_data)},
        )
        return override
