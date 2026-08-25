from rest_framework import serializers

from addresses.domain.address_type import AddressType
from addresses.validators import validate_coordinates


class AddressWriteSerializer(serializers.Serializer):
    """
    Address book write payload. User identity fields (first_name, last_name,
    country_code, phone, title) are populated automatically from the authenticated user.
    """

    address_type = serializers.ChoiceField(
        choices=AddressType.choices,
        required=False,
        default=AddressType.HOME,
        help_text="Address label category (Home, Work, Office, etc.).",
    )
    custom_label = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text="Required when address_type is OTHER.",
    )
    # Legacy alias for address_type
    label = serializers.CharField(max_length=20, required=False, allow_blank=True)

    # Legacy clients may still send these; they are ignored by AddressDomainService.
    first_name = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Deprecated. Populated automatically from the authenticated user.",
    )
    last_name = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Deprecated. Populated automatically from the authenticated user.",
    )
    country_code = serializers.CharField(
        max_length=5,
        required=False,
        allow_blank=True,
        help_text="Deprecated. Populated automatically from the authenticated user.",
    )
    title = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="Deprecated. Derived from address_type by the backend.",
    )
    phone = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        help_text="Deprecated. Populated automatically from the authenticated user.",
    )

    company = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    country = serializers.CharField(max_length=2)
    province = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    street = serializers.CharField(max_length=500)
    building_number = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    floor = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    postal_code = serializers.CharField(max_length=20)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    delivery_notes = serializers.CharField(required=False, allow_blank=True, default="")
    is_default = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        validate_coordinates(attrs.get("latitude"), attrs.get("longitude"))
        if attrs.get("address_type") == AddressType.OTHER and not attrs.get("custom_label"):
            raise serializers.ValidationError(
                {"custom_label": "Required when address_type is OTHER."}
            )
        return attrs


class AddressUpdateSerializer(AddressWriteSerializer):
    address_type = serializers.ChoiceField(choices=AddressType.choices, required=False)
    custom_label = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.CharField(max_length=2, required=False)
    city = serializers.CharField(max_length=100, required=False)
    street = serializers.CharField(max_length=500, required=False)
    postal_code = serializers.CharField(max_length=20, required=False)

    def validate(self, attrs):
        validate_coordinates(attrs.get("latitude"), attrs.get("longitude"))
        if attrs.get("address_type") == AddressType.OTHER and "custom_label" in attrs and not attrs.get("custom_label"):
            raise serializers.ValidationError(
                {"custom_label": "Required when address_type is OTHER."}
            )
        return attrs


class LegacyAddressWriteSerializer(serializers.Serializer):
    """Backward-compatible payload for /api/orders/addresses/."""

    label = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    street = serializers.CharField(max_length=500)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    zip = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)
    is_default = serializers.BooleanField(required=False, default=False)

    def to_internal_value(self, data):
        from addresses.services.address_domain_service import AddressDomainService

        validated = super().to_internal_value(data)
        return AddressDomainService().normalize({
            "address_type": validated.get("label", "home"),
            "country": "US",
            "province": validated.get("state", ""),
            "city": validated["city"],
            "street": validated["street"],
            "postal_code": validated.get("zip") or "00000",
            "latitude": validated.get("lat"),
            "longitude": validated.get("lng"),
            "is_default": validated.get("is_default", False),
        })
