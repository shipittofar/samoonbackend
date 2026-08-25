from rest_framework import serializers

from tenants.branding import TenantBranding


class TenantBrandingSerializer(serializers.Serializer):
    """Read-only projection of ``TenantBranding``."""

    primaryColor = serializers.CharField(read_only=True, required=False)
    accentHoverColor = serializers.CharField(read_only=True, required=False)
    fontBody = serializers.CharField(read_only=True, required=False)
    fontsByLocale = serializers.DictField(
        child=serializers.CharField(),
        read_only=True,
        required=False,
    )

    def to_representation(self, instance):
        if isinstance(instance, TenantBranding):
            data = {}
            if instance.primaryColor is not None:
                data["primaryColor"] = instance.primaryColor
            if instance.accentHoverColor is not None:
                data["accentHoverColor"] = instance.accentHoverColor
            if instance.fontBody is not None:
                data["fontBody"] = instance.fontBody
            if instance.fontsByLocale:
                data["fontsByLocale"] = instance.fontsByLocale
            return data
        return super().to_representation(instance)
