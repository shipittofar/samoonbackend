from rest_framework import serializers

from addresses.domain.address_type import display_label
from addresses.models import Address


class AddressResponseSerializer(serializers.ModelSerializer):
    title = serializers.CharField(
        read_only=True,
        help_text="Address label derived from address_type (e.g. Home, Work).",
    )
    address_type = serializers.CharField(read_only=True)
    custom_label = serializers.CharField(read_only=True)
    label = serializers.SerializerMethodField()
    type_display = serializers.CharField(read_only=True)
    capabilities = serializers.SerializerMethodField()

    first_name = serializers.CharField(read_only=True, help_text="Populated from authenticated user profile.")
    last_name = serializers.CharField(read_only=True, help_text="Populated from authenticated user profile.")
    country_code = serializers.CharField(read_only=True, help_text="Populated from authenticated user profile.")
    phone = serializers.CharField(read_only=True, help_text="Populated from authenticated user profile.")

    class Meta:
        model = Address
        fields = [
            "id",
            "uuid",
            "title",
            "address_type",
            "custom_label",
            "label",
            "type_display",
            "first_name",
            "last_name",
            "company",
            "phone",
            "country_code",
            "country",
            "province",
            "city",
            "district",
            "street",
            "building_number",
            "unit",
            "floor",
            "postal_code",
            "latitude",
            "longitude",
            "formatted_address",
            "delivery_notes",
            "is_default",
            "verification_status",
            "is_verified",
            "verified_at",
            "verification_source",
            "capabilities",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_label(self, obj) -> str:
        return display_label(obj.address_type, obj.custom_label)

    def get_capabilities(self, obj) -> dict | None:
        caps = self.context.get("capabilities")
        if caps is not None:
            return caps
        branch = self.context.get("branch")
        if branch is None:
            return None
        domain = self.context.get("domain_service")
        if domain is None:
            from addresses.services.address_domain_service import AddressDomainService
            domain = AddressDomainService()
        return domain.get_capabilities(user=self.context["request"].user, address=obj, branch=branch)


class LegacyAddressResponseSerializer(serializers.ModelSerializer):
    """Maps new Address model fields to the legacy /api/orders/addresses/ shape."""

    id = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    state = serializers.CharField(source="province")
    zip = serializers.CharField(source="postal_code")
    lat = serializers.FloatField(source="latitude", allow_null=True)
    lng = serializers.FloatField(source="longitude", allow_null=True)

    class Meta:
        model = Address
        fields = ["id", "label", "street", "city", "state", "zip", "lat", "lng", "is_default", "formatted_address"]

    def get_id(self, obj) -> int:
        return obj.legacy_id or 0

    def get_label(self, obj) -> str:
        return display_label(obj.address_type, obj.custom_label)
