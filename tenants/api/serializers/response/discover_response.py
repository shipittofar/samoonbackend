from rest_framework import serializers

from tenants.api.serializers.response.branding import TenantBrandingSerializer
from tenants.branding import (
    build_legacy_discover_theme,
    build_tenant_branding,
    resolve_tenant_image_url,
)
from tenants.services.branch_availability import get_branch_availability
from tenants.services.discover_marketplace import (
    build_marketplace_metadata,
    get_public_branches,
)


class DiscoverBranchLocationResponseSerializer(serializers.Serializer):
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    country = serializers.CharField(read_only=True)


class DiscoverBranchResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    image = serializers.SerializerMethodField()
    cuisines = serializers.ListField(child=serializers.CharField(), read_only=True)
    amenities = serializers.ListField(child=serializers.CharField(), read_only=True)
    openNow = serializers.SerializerMethodField()
    todayHours = serializers.SerializerMethodField()
    location = DiscoverBranchLocationResponseSerializer(source="*", read_only=True)

    def get_image(self, obj) -> str | None:
        return getattr(obj, "image_url", None)

    def _availability_cache(self) -> dict:
        return self.context.setdefault("branch_availability_cache", {})

    def _get_availability(self, obj) -> dict:
        cache = self._availability_cache()
        key = getattr(obj, "id", None) or id(obj)
        if key not in cache:
            cache[key] = get_branch_availability(obj)
        return cache[key]

    def get_openNow(self, obj) -> bool:
        return self._get_availability(obj)["openNow"]

    def get_todayHours(self, obj) -> str | None:
        return self._get_availability(obj)["todayHours"]


class DiscoverTenantResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    image = serializers.SerializerMethodField()
    businessTypes = serializers.SerializerMethodField()
    featureFlags = serializers.SerializerMethodField()
    branding = serializers.SerializerMethodField()
    theme = serializers.SerializerMethodField()
    marketplace = serializers.SerializerMethodField()
    branches = DiscoverBranchResponseSerializer(many=True, read_only=True)

    def get_businessTypes(self, obj) -> list[str]:
        return list(getattr(obj, "business_types", None) or [])

    def get_featureFlags(self, obj) -> dict:
        return (getattr(obj, "settings", None) or {}).get("featureFlags") or {}

    def get_image(self, obj) -> str | None:
        return resolve_tenant_image_url(obj)

    def get_branding(self, obj) -> dict:
        branding = build_tenant_branding(obj)
        return TenantBrandingSerializer(branding).data

    def get_theme(self, obj) -> dict:
        branding = build_tenant_branding(obj)
        return build_legacy_discover_theme(branding)

    def get_marketplace(self, obj) -> dict:
        public_branches = get_public_branches(obj)
        return build_marketplace_metadata(obj, public_branches)
