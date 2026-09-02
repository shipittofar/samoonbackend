import json

from rest_framework import serializers

from tenants.api.serializers.fields import BusinessTypesField
from tenants.models import (
    TenantStatus,
    BranchStatus,
    WorkingHour,
    BranchType,
    BranchOrderType,
    BranchPaymentMethod,
)
from tenants.checkout_config import (
    flatten_nested_checkout,
    map_checkout_camel_to_snake,
    strip_operational_settings_keys,
)
from tenants.settings_cleanup import (
    TenantSettingsContractError,
    validate_tenant_settings_contract,
)


class WorkingHourSerializer(serializers.Serializer):
    day = serializers.ChoiceField(choices=WorkingHour.Weekday.choices)
    open_time = serializers.TimeField(required=False, allow_null=True)
    close_time = serializers.TimeField(required=False, allow_null=True)
    is_closed = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("is_closed"):
            if not attrs.get("open_time") or not attrs.get("close_time"):
                raise serializers.ValidationError(
                    "open_time and close_time are required when is_closed is False."
                )
        return attrs


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    tax_percentage = serializers.DecimalField(
        max_digits=4, decimal_places=2,
        required=False, default=0,
        min_value=0, max_value=100,
    )

    service_charge_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        required=False, default=0,
        min_value=0, max_value=100,
    )

    image = serializers.ImageField(required=False, allow_null=True)
    discover_avatar = serializers.ImageField(required=False, allow_null=True)
    discover_cover = serializers.ImageField(required=False, allow_null=True)
    hero_image = serializers.ImageField(required=False, allow_null=True)

    business_types = BusinessTypesField(required=False, default=list)
    status = serializers.ChoiceField(
        choices=TenantStatus.choices,
        required=False,
        default=TenantStatus.INACTIVE,
    )

    settings = serializers.JSONField(required=False, default=dict)

    def validate_settings(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("settings must be a JSON object.")
        try:
            return validate_tenant_settings_contract(value)
        except TenantSettingsContractError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def to_internal_value(self, data):
        data = data.dict() if hasattr(data, "dict") else dict(data)

        if "businessTypes" in data and "business_types" not in data:
            data["business_types"] = data.pop("businessTypes")

        if "serviceChargePercentage" in data and "service_charge_percentage" not in data:
            data["service_charge_percentage"] = data.pop("serviceChargePercentage")

        if "discoverAvatar" in data and "discover_avatar" not in data:
            data["discover_avatar"] = data["discoverAvatar"]
        if "discoverCover" in data and "discover_cover" not in data:
            data["discover_cover"] = data["discoverCover"]
        if "heroImage" in data and "hero_image" not in data:
            data["hero_image"] = data["heroImage"]

        settings_raw = data.get("settings")
        if isinstance(settings_raw, str):
            try:
                data["settings"] = json.loads(settings_raw)
            except (TypeError, ValueError):
                raise serializers.ValidationError({"settings": "Invalid JSON format."})

        return super().to_internal_value(data)


class TenantUpdateSerializer(TenantCreateSerializer):
    """Same shape as create; kept as a subclass so future field-level
    differences don't have to be duplicated by hand."""
    pass


class BranchCheckoutConfigSerializer(serializers.Serializer):
    """Typed checkout configuration — camelCase API fields."""

    deliveryEnabled = serializers.BooleanField(required=False)
    pickupEnabled = serializers.BooleanField(required=False)
    tableOrderingEnabled = serializers.BooleanField(required=False)
    orderingEnabled = serializers.BooleanField(required=False)
    deliveryRadius = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    minimumOrder = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0,
    )
    defaultOrderType = serializers.ChoiceField(
        choices=BranchOrderType.choices, required=False, allow_null=True,
    )
    cashPaymentEnabled = serializers.BooleanField(required=False)
    cardPaymentEnabled = serializers.BooleanField(required=False)
    onlinePaymentEnabled = serializers.BooleanField(required=False)
    walletPaymentEnabled = serializers.BooleanField(required=False)
    cashOnDeliveryEnabled = serializers.BooleanField(required=False)
    defaultPaymentMethod = serializers.ChoiceField(
        choices=BranchPaymentMethod.choices, required=False, allow_null=True,
    )
    sameDayDeliveryEnabled = serializers.BooleanField(required=False)
    scheduledDeliveryEnabled = serializers.BooleanField(required=False)
    contactlessDeliveryEnabled = serializers.BooleanField(required=False)
    marketplaceVisible = serializers.BooleanField(required=False)
    reservationsEnabled = serializers.BooleanField(required=False)
    maxCapacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)


WEEKDAY_LABEL_TO_VALUE = {
    label: value for value, label in WorkingHour.Weekday.choices
}


class BranchLocationCreateSerializer(serializers.Serializer):
    address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    postalCode = serializers.CharField(required=False, allow_blank=True, max_length=20)
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True,
        min_value=-90, max_value=90,
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True,
        min_value=-180, max_value=180,
    )


class BranchContactCreateSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)


class BranchBusinessHoursCreateSerializer(serializers.Serializer):
    day = serializers.ChoiceField(
        choices=[label for _, label in WorkingHour.Weekday.choices],
    )
    open = serializers.TimeField(required=False, allow_null=True)
    close = serializers.TimeField(required=False, allow_null=True)
    isClosed = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("isClosed"):
            if not attrs.get("open") or not attrs.get("close"):
                raise serializers.ValidationError(
                    "open and close are required when isClosed is False."
                )
        return attrs


class BranchConsoleCreateSerializer(serializers.Serializer):
    """Console branch create — accepts the frontend nested camelCase contract.

    Outputs flat snake_case ``validated_data`` for ``BranchBusinessLogicLayer.create_branch``.
    Legacy flat snake_case request bodies are still accepted for backward compatibility.
    ``slug`` is intentionally not a field and is always ignored.
    """

    name = serializers.CharField(
        max_length=255, required=False, allow_blank=True,
        help_text="Optional — leave blank for single-branch tenants.",
    )
    description = serializers.CharField(required=False, allow_blank=True)
    type = serializers.ChoiceField(
        choices=BranchType.choices, required=False, default=BranchType.PHYSICAL,
    )
    location = BranchLocationCreateSerializer(required=False)
    contact = BranchContactCreateSerializer(required=False)
    businessHours = BranchBusinessHoursCreateSerializer(many=True, required=False)
    settings = serializers.JSONField(required=False)
    isDefault = serializers.BooleanField(required=False, default=False)

    # Top-level typed checkout fields (camelCase)
    deliveryEnabled = serializers.BooleanField(required=False)
    pickupEnabled = serializers.BooleanField(required=False)
    tableOrderingEnabled = serializers.BooleanField(required=False)
    orderingEnabled = serializers.BooleanField(required=False)
    deliveryRadius = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    minimumOrder = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0,
    )
    defaultOrderType = serializers.ChoiceField(
        choices=BranchOrderType.choices, required=False, allow_null=True,
    )
    cashPaymentEnabled = serializers.BooleanField(required=False)
    cardPaymentEnabled = serializers.BooleanField(required=False)
    onlinePaymentEnabled = serializers.BooleanField(required=False)
    walletPaymentEnabled = serializers.BooleanField(required=False)
    cashOnDeliveryEnabled = serializers.BooleanField(required=False)
    defaultPaymentMethod = serializers.ChoiceField(
        choices=BranchPaymentMethod.choices, required=False, allow_null=True,
    )
    sameDayDeliveryEnabled = serializers.BooleanField(required=False)
    scheduledDeliveryEnabled = serializers.BooleanField(required=False)
    contactlessDeliveryEnabled = serializers.BooleanField(required=False)
    marketplaceVisible = serializers.BooleanField(required=False)
    reservationsEnabled = serializers.BooleanField(required=False)
    maxCapacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    cuisines = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    amenities = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    image = serializers.ImageField(required=False, allow_null=True)
    coverImage = serializers.ImageField(
        required=False, allow_null=True, source="cover_image",
    )
    heroImage = serializers.ImageField(
        required=False, allow_null=True, source="hero_image",
    )

    def validate_businessHours(self, value):
        days = [entry["day"] for entry in value]
        if len(days) != len(set(days)):
            raise serializers.ValidationError(
                "Duplicate day found in businessHours."
            )
        return value

    def validate(self, attrs):
        location = attrs.pop("location", None) or {}
        contact = attrs.pop("contact", None) or {}
        business_hours_input = attrs.pop("businessHours", None) or []

        attrs["address"] = location.get("address", "")
        attrs["city"] = location.get("city", "")
        attrs["country"] = location.get("country", "")
        attrs["postal_code"] = location.get("postalCode", "")
        if "latitude" in location:
            attrs["latitude"] = location.get("latitude")
        if "longitude" in location:
            attrs["longitude"] = location.get("longitude")

        attrs["phone"] = contact.get("phone_number", "")
        attrs["email"] = contact.get("email", "")
        attrs["website"] = contact.get("website", "")

        attrs["working_hours"] = [
            {
                "day": WEEKDAY_LABEL_TO_VALUE[entry["day"]],
                "open_time": entry.get("open"),
                "close_time": entry.get("close"),
                "is_closed": entry.get("isClosed", False),
            }
            for entry in business_hours_input
        ]

        attrs["is_default"] = attrs.pop("isDefault", False)

        if attrs.get("settings") is not None:
            attrs["settings"] = strip_operational_settings_keys(attrs["settings"])

        return map_checkout_camel_to_snake(attrs)

    def to_internal_value(self, data):
        data = data.dict() if hasattr(data, "dict") else dict(data)

        for field in ("settings", "businessHours", "location", "contact", "metadata"):
            raw = data.get(field)
            if isinstance(raw, str):
                try:
                    data[field] = json.loads(raw)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {field: "Invalid JSON format."}
                    )

        # Legacy flat snake_case bodies (pre-console contract).
        if "location" not in data and any(
            key in data for key in ("address", "city", "country", "postal_code")
        ):
            data["location"] = {
                "address": data.get("address", ""),
                "city": data.get("city", ""),
                "country": data.get("country", ""),
                "postalCode": data.get("postal_code", ""),
            }
            if "latitude" in data:
                data["location"]["latitude"] = data["latitude"]
            if "longitude" in data:
                data["location"]["longitude"] = data["longitude"]

        if "contact" not in data and any(
            key in data for key in ("phone", "email", "website")
        ):
            data["contact"] = {
                "phone_number": data.get("phone", ""),
                "email": data.get("email", ""),
                "website": data.get("website", ""),
            }

        if "businessHours" not in data and "working_hours" in data:
            legacy_hours = data.get("working_hours") or []
            if isinstance(legacy_hours, str):
                try:
                    legacy_hours = json.loads(legacy_hours)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {"working_hours": "Invalid JSON format."}
                    )
            data["businessHours"] = []
            for entry in legacy_hours:
                day = entry.get("day")
                if isinstance(day, int):
                    day = WorkingHour.Weekday(day).label
                data["businessHours"].append({
                    "day": day,
                    "open": entry.get("open_time"),
                    "close": entry.get("close_time"),
                    "isClosed": entry.get("is_closed", False),
                })

        if "isDefault" not in data and "is_default" in data:
            data["isDefault"] = data["is_default"]

        return super().to_internal_value(data)


class BranchCreateSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=255, required=False, allow_blank=True,
        help_text="Optional — leave blank for single-branch tenants.",
    )

    type = serializers.ChoiceField(
        choices=BranchType.choices, required=False, default=BranchType.PHYSICAL,
    )

    manager = serializers.UUIDField(required=False, allow_null=True)

    # --- contact ---
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)

    # --- location ---
    address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=20)

    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True,
        min_value=-90, max_value=90,
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True,
        min_value=-180, max_value=180,
    )

    # --- media ---
    image = serializers.ImageField(required=False, allow_null=True)
    cover_image = serializers.ImageField(required=False, allow_null=True)
    hero_image = serializers.ImageField(required=False, allow_null=True)

    # --- locale ---
    time_zone = serializers.CharField(required=False, allow_blank=True, max_length=64, default="UTC")
    currency = serializers.CharField(required=False, allow_blank=True, max_length=10, default="USD")
    language = serializers.CharField(required=False, allow_blank=True, max_length=10, default="en")

    # --- checkout (typed columns) ---
    ordering_enabled = serializers.BooleanField(required=False)
    delivery_enabled = serializers.BooleanField(required=False)
    pickup_enabled = serializers.BooleanField(required=False)
    table_ordering_enabled = serializers.BooleanField(required=False)
    default_order_type = serializers.ChoiceField(
        choices=BranchOrderType.choices, required=False, allow_null=True,
    )
    delivery_radius_km = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    minimum_order_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0,
    )
    same_day_delivery_enabled = serializers.BooleanField(required=False)
    scheduled_delivery_enabled = serializers.BooleanField(required=False)
    contactless_delivery_enabled = serializers.BooleanField(required=False)
    cash_on_delivery_enabled = serializers.BooleanField(required=False)
    cash_payment_enabled = serializers.BooleanField(required=False)
    card_payment_enabled = serializers.BooleanField(required=False)
    online_payment_enabled = serializers.BooleanField(required=False)
    wallet_payment_enabled = serializers.BooleanField(required=False)
    default_payment_method = serializers.ChoiceField(
        choices=BranchPaymentMethod.choices, required=False, allow_null=True,
    )
    marketplace_visible = serializers.BooleanField(required=False)
    reservations_enabled = serializers.BooleanField(required=False)
    max_capacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    cuisines = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
    )
    amenities = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
    )

    # --- extension settings only ---
    settings = serializers.JSONField(required=False)
    metadata = serializers.DictField(required=False, default=dict)

    status = serializers.ChoiceField(
        choices=BranchStatus.choices,
        required=False,
        default=BranchStatus.ACTIVE,
    )
    is_active = serializers.BooleanField(required=False, default=True)
    is_default = serializers.BooleanField(required=False, default=False)

    working_hours = WorkingHourSerializer(many=True, required=False)

    def validate_working_hours(self, value):
        days = [wh["day"] for wh in value]
        if len(days) != len(set(days)):
            raise serializers.ValidationError(
                "Duplicate day found in working_hours."
            )
        return value

    def validate(self, attrs):
        if attrs.get("settings") is not None:
            attrs["settings"] = strip_operational_settings_keys(attrs["settings"])
        return attrs

    def to_internal_value(self, data):
        data = data.dict() if hasattr(data, "dict") else dict(data)

        if "coverImage" in data and "cover_image" not in data:
            data["cover_image"] = data["coverImage"]
        if "heroImage" in data and "hero_image" not in data:
            data["hero_image"] = data["heroImage"]

        # multipart/form-data sends these as JSON strings — decode before validation
        for field in ("working_hours", "settings", "metadata", "cuisines", "amenities"):
            raw = data.get(field)
            if isinstance(raw, str):
                try:
                    data[field] = json.loads(raw)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {field: "Invalid JSON format."}
                    )

        return super().to_internal_value(data)


class BranchUpdateSerializer(BranchCreateSerializer):
    """Same shape as create — full-replace update semantics."""
    pass


class BranchConsoleUpdateSerializer(BranchConsoleCreateSerializer):
    """Console branch update — frontend nested camelCase contract (PATCH, partial)."""

    image = serializers.ImageField(required=False, allow_null=True)
    coverImage = serializers.ImageField(
        required=False, allow_null=True, source="cover_image",
    )
    heroImage = serializers.ImageField(
        required=False, allow_null=True, source="hero_image",
    )

    _JSON_STRING_FIELDS = (
        "settings", "businessHours", "location", "contact", "metadata", "checkout",
        "cuisines", "amenities",
    )

    def validate(self, attrs):
        if getattr(self, "partial", False):
            return self._validate_partial(attrs)
        return super().validate(attrs)

    def _validate_partial(self, attrs):
        if "location" in attrs:
            location = attrs.pop("location") or {}
            location_map = {
                "address": "address",
                "city": "city",
                "country": "country",
                "postalCode": "postal_code",
                "latitude": "latitude",
                "longitude": "longitude",
            }
            for src, dest in location_map.items():
                if src in location:
                    attrs[dest] = location[src]

        if "contact" in attrs:
            contact = attrs.pop("contact") or {}
            contact_map = {
                "phone_number": "phone",
                "email": "email",
                "website": "website",
            }
            for src, dest in contact_map.items():
                if src in contact:
                    attrs[dest] = contact[src]

        if "businessHours" in attrs:
            business_hours_input = attrs.pop("businessHours") or []
            attrs["working_hours"] = [
                {
                    "day": WEEKDAY_LABEL_TO_VALUE[entry["day"]],
                    "open_time": entry.get("open"),
                    "close_time": entry.get("close"),
                    "is_closed": entry.get("isClosed", False),
                }
                for entry in business_hours_input
            ]

        if "isDefault" in attrs:
            attrs["is_default"] = attrs.pop("isDefault")

        if attrs.get("settings") is not None:
            attrs["settings"] = strip_operational_settings_keys(attrs["settings"])

        return map_checkout_camel_to_snake(attrs)

    def to_internal_value(self, data):
        data = data.dict() if hasattr(data, "dict") else dict(data)

        for field in ("image", "coverImage", "cover_image", "heroImage", "hero_image"):
            if data.get(field) == "":
                data.pop(field, None)

        checkout_raw = data.get("checkout")
        if isinstance(checkout_raw, str):
            try:
                checkout_raw = json.loads(checkout_raw)
            except (TypeError, ValueError):
                raise serializers.ValidationError({"checkout": "Invalid JSON format."})
        if isinstance(checkout_raw, dict):
            for key, value in flatten_nested_checkout(checkout_raw).items():
                data.setdefault(key, value)
            data.pop("checkout", None)

        for field in self._JSON_STRING_FIELDS:
            raw = data.get(field)
            if isinstance(raw, str):
                try:
                    data[field] = json.loads(raw)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {field: "Invalid JSON format."}
                    )

        if "location" not in data and any(
            key in data for key in ("address", "city", "country", "postal_code")
        ):
            data["location"] = {
                "address": data.get("address", ""),
                "city": data.get("city", ""),
                "country": data.get("country", ""),
                "postalCode": data.get("postal_code", ""),
            }
            if "latitude" in data:
                data["location"]["latitude"] = data["latitude"]
            if "longitude" in data:
                data["location"]["longitude"] = data["longitude"]

        if "contact" not in data and any(
            key in data for key in ("phone", "email", "website")
        ):
            data["contact"] = {
                "phone_number": data.get("phone", ""),
                "email": data.get("email", ""),
                "website": data.get("website", ""),
            }

        if "businessHours" not in data and "working_hours" in data:
            legacy_hours = data.get("working_hours") or []
            if isinstance(legacy_hours, str):
                try:
                    legacy_hours = json.loads(legacy_hours)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {"working_hours": "Invalid JSON format."}
                    )
            data["businessHours"] = []
            for entry in legacy_hours:
                day = entry.get("day")
                if isinstance(day, int):
                    day = WorkingHour.Weekday(day).label
                data["businessHours"].append({
                    "day": day,
                    "open": entry.get("open_time"),
                    "close": entry.get("close_time"),
                    "isClosed": entry.get("is_closed", False),
                })

        if "isDefault" not in data and "is_default" in data:
            data["isDefault"] = data["is_default"]

        return super(BranchConsoleCreateSerializer, self).to_internal_value(data)