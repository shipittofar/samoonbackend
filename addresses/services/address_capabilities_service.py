from __future__ import annotations

from typing import Any

from addresses.services.delivery_zone_service import DeliveryZoneResult


class AddressCapabilitiesService:
    """
    Resolution order:

    1. Branch / delivery-zone rules (typed operational fields)
    2. Tenant or Branch ``addressCapabilities`` boolean overlay
    3. computed capability result

    Overlay keys are an open string → bool map. This is not a replacement
    for Branch operational columns (delivery_enabled, etc.).
    """

    CAPABILITY_RULES = (
        ("can_deliver", lambda ctx: ctx["zone"].serviceable and ctx["zone"].available),
        ("supports_same_day", lambda ctx: ctx["branch"].same_day_delivery_enabled),
        ("supports_scheduled_delivery", lambda ctx: ctx["branch"].scheduled_delivery_enabled),
        ("supports_cash_on_delivery", lambda ctx: ctx["branch"].cash_on_delivery_enabled),
        ("supports_contactless_delivery", lambda ctx: ctx["branch"].contactless_delivery_enabled),
    )

    def resolve(
        self,
        *,
        branch,
        tenant,
        zone: DeliveryZoneResult,
    ) -> dict[str, bool]:
        branch_settings = branch.settings or {}
        tenant_settings = getattr(tenant, "settings", None) or {}
        ctx = {
            "branch": branch,
            "tenant": tenant,
            "zone": zone,
            "tenant_settings": tenant_settings,
        }
        capabilities: dict[str, bool] = {}
        for key, rule in self.CAPABILITY_RULES:
            capabilities[key] = bool(rule(ctx))
        extra = tenant_settings.get("addressCapabilities") or branch_settings.get("addressCapabilities") or {}
        for key, value in extra.items():
            if isinstance(value, bool):
                capabilities[key] = value
        return capabilities
