from rest_framework import serializers

from menu.models import MenuTemplate
from menu.services.template_bll import validate_content
from tenants.constants.business_type import BusinessType
from tenants.models import BusinessRequest


def _user_block(user) -> dict | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "phone_number": user.phone_number,
        "email": user.email,
        "full_name": user.full_name,
    }


class PlatformTenantListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    is_active = serializers.BooleanField()
    business_types = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    branch_count = serializers.IntegerField()
    city = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    owner_status = serializers.SerializerMethodField()

    def get_owner(self, tenant):
        return _user_block(tenant.owner.user)

    def get_owner_status(self, tenant):
        return tenant.owner.status or "active"

    def get_city(self, tenant):
        return getattr(tenant, "first_city", None) or ""


class MenuTemplateSerializer(serializers.ModelSerializer):
    business_type = serializers.ChoiceField(choices=BusinessType.choices)
    category_count = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MenuTemplate
        fields = [
            "id", "name", "description", "business_type", "is_active", "content",
            "category_count", "item_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_category_count(self, obj) -> int:
        return len(obj.categories)

    def validate_content(self, value):
        return validate_content(value)


class BusinessRequestSerializer(serializers.ModelSerializer):
    """What the applicant sends and sees."""

    business_type = serializers.ChoiceField(choices=BusinessType.choices)
    tenant_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = BusinessRequest
        fields = [
            "id", "status", "name", "business_type", "description", "phone", "city",
            "address", "latitude", "longitude", "service_radius_km",
            "rejection_reason", "tenant_id", "created_at", "decided_at",
        ]
        read_only_fields = ["id", "status", "rejection_reason", "tenant_id", "created_at", "decided_at"]

    def validate(self, attrs):
        if (attrs.get("latitude") is None) != (attrs.get("longitude") is None):
            raise serializers.ValidationError("latitude and longitude go together.")
        lat, lng = attrs.get("latitude"), attrs.get("longitude")
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise serializers.ValidationError("Location is out of range.")
        radius = attrs.get("service_radius_km")
        if radius is not None and radius > 200:
            raise serializers.ValidationError({"service_radius_km": "At most 200 km."})
        return attrs


class PlatformBusinessRequestSerializer(BusinessRequestSerializer):
    """What superusers see: plus the applicant and who decided."""

    applicant = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()

    class Meta(BusinessRequestSerializer.Meta):
        fields = BusinessRequestSerializer.Meta.fields + ["applicant", "decided_by"]

    def get_applicant(self, obj):
        return _user_block(obj.user)

    def get_decided_by(self, obj):
        return _user_block(obj.decided_by)
