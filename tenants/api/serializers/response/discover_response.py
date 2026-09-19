from rest_framework import serializers

from tenants.api.serializers.response.branding import TenantBrandingSerializer
from tenants.api.serializers.response.qr import serialize_qr
from tenants.api.serializers.response.tenant_response import _media_url
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
    coverImage = serializers.SerializerMethodField()
    heroImage = serializers.SerializerMethodField()
    cuisines = serializers.ListField(child=serializers.CharField(), read_only=True)
    amenities = serializers.ListField(child=serializers.CharField(), read_only=True)
    openNow = serializers.SerializerMethodField()
    todayHours = serializers.SerializerMethodField()
    location = DiscoverBranchLocationResponseSerializer(source="*", read_only=True)
    qr = serializers.SerializerMethodField()

    def get_image(self, obj) -> str | None:
        return _media_url(obj, "image", "image_url")

    def get_coverImage(self, obj) -> str | None:
        return _media_url(obj, "cover_image", "cover_image_url")

    def get_heroImage(self, obj) -> str | None:
        return _media_url(obj, "hero_image", "hero_image_url")

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

    def get_qr(self, obj):
        return serialize_qr(obj, self.context.get("request"))


class DiscoverTenantResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    image = serializers.SerializerMethodField()
    discoverAvatar = serializers.SerializerMethodField()
    discoverCover = serializers.SerializerMethodField()
    heroImage = serializers.SerializerMethodField()
    businessTypes = serializers.SerializerMethodField()
    featureFlags = serializers.SerializerMethodField()
    branding = serializers.SerializerMethodField()
    theme = serializers.SerializerMethodField()
    marketplace = serializers.SerializerMethodField()
    branches = DiscoverBranchResponseSerializer(many=True, read_only=True)
    qr = serializers.SerializerMethodField()

    def get_businessTypes(self, obj) -> list[str]:
        return list(getattr(obj, "business_types", None) or [])

    def get_featureFlags(self, obj) -> dict:
        """Public catalog overlay of tenant.settings.featureFlags.

        Kept: DiscoverTenant and public-context resolve menu/ordering/
        reservations/loyalty from this field. These are not entitlements
        and are not equivalent to Branch operational capabilities.
        """
        return (getattr(obj, "settings", None) or {}).get("featureFlags") or {}

    def get_image(self, obj) -> str | None:
        return resolve_tenant_image_url(obj)

    def get_discoverAvatar(self, obj) -> str | None:
        return _media_url(obj, "discover_avatar", "discover_avatar_url")

    def get_discoverCover(self, obj) -> str | None:
        return _media_url(obj, "discover_cover", "discover_cover_url")

    def get_heroImage(self, obj) -> str | None:
        return _media_url(obj, "hero_image", "hero_image_url")

    def get_branding(self, obj) -> dict:
        branding = build_tenant_branding(obj)
        return TenantBrandingSerializer(branding).data

    def get_theme(self, obj) -> dict:
        branding = build_tenant_branding(obj)
        return build_legacy_discover_theme(branding)

    def get_marketplace(self, obj) -> dict:
        public_branches = get_public_branches(obj)
        return build_marketplace_metadata(obj, public_branches)

    def get_qr(self, obj):
        return serialize_qr(obj, self.context.get("request"))
