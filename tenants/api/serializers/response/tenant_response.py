from rest_framework import serializers

from tenants.api.serializers.fields import BusinessTypesField
from tenants.api.serializers.response.tenant_summary import (
    TenantSummarySerializer,
    build_tenant_summary,
)
from tenants.models import WorkingHour
from tenants.settings_cleanup import (
    project_owner_tenant_settings,
    project_public_tenant_settings,
)


WEEKDAY_LABELS = dict(WorkingHour.Weekday.choices)


def _media_url(obj, name_attr: str = "image", url_attr: str = "image_url"):
    url = getattr(obj, url_attr, None)
    if url:
        return url
    field = getattr(obj, name_attr, None)
    if not field:
        return None
    if isinstance(field, str):
        return field
    try:
        return field.url
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Working hours -> businessHours
# ---------------------------------------------------------------------------

class BranchBusinessHoursResponseSerializer(serializers.Serializer):
    day = serializers.SerializerMethodField()
    open = serializers.SerializerMethodField()
    close = serializers.SerializerMethodField()
    isClosed = serializers.BooleanField(source="is_closed", read_only=True)

    def get_day(self, obj) -> str:
        if hasattr(obj, "get_day_display"):
            return obj.get_day_display()
        return WEEKDAY_LABELS.get(obj.day, str(obj.day))

    def get_open(self, obj) -> str | None:
        return obj.open_time.strftime("%H:%M") if obj.open_time else None

    def get_close(self, obj) -> str | None:
        return obj.close_time.strftime("%H:%M") if obj.close_time else None


# ---------------------------------------------------------------------------
# Nested groupings
# ---------------------------------------------------------------------------

class BranchLocationResponseSerializer(serializers.Serializer):
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    country = serializers.CharField(read_only=True)
    postalCode = serializers.CharField(source="postal_code", read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, read_only=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, read_only=True)


class BranchContactResponseSerializer(serializers.Serializer):
    phone_number = serializers.CharField(source="phone", read_only=True)
    email = serializers.EmailField(read_only=True)
    website = serializers.URLField(read_only=True)


class CheckoutOrderTypesSerializer(serializers.Serializer):
    delivery = serializers.BooleanField(source="delivery_enabled", read_only=True)
    pickup = serializers.BooleanField(source="pickup_enabled", read_only=True)
    dineIn = serializers.BooleanField(source="table_ordering_enabled", read_only=True)
    default = serializers.CharField(source="default_order_type", read_only=True, allow_null=True)


class CheckoutPaymentsSerializer(serializers.Serializer):
    cash = serializers.BooleanField(source="cash_payment_enabled", read_only=True)
    cashOnDelivery = serializers.BooleanField(source="cash_on_delivery_enabled", read_only=True)
    card = serializers.BooleanField(source="card_payment_enabled", read_only=True)
    online = serializers.BooleanField(source="online_payment_enabled", read_only=True)
    wallet = serializers.BooleanField(source="wallet_payment_enabled", read_only=True)
    default = serializers.CharField(source="default_payment_method", read_only=True, allow_null=True)


class CheckoutDeliverySerializer(serializers.Serializer):
    radius = serializers.IntegerField(source="delivery_radius_km", read_only=True, allow_null=True)
    minimumOrder = serializers.DecimalField(
        source="minimum_order_amount",
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    sameDay = serializers.BooleanField(source="same_day_delivery_enabled", read_only=True)
    scheduled = serializers.BooleanField(source="scheduled_delivery_enabled", read_only=True)
    contactless = serializers.BooleanField(source="contactless_delivery_enabled", read_only=True)


class CheckoutConfigurationSerializer(serializers.Serializer):
    orderingEnabled = serializers.BooleanField(source="ordering_enabled", read_only=True)
    orderTypes = CheckoutOrderTypesSerializer(source="*", read_only=True)
    payments = CheckoutPaymentsSerializer(source="*", read_only=True)
    delivery = CheckoutDeliverySerializer(source="*", read_only=True)


class BranchCheckoutResponseMixin(serializers.Serializer):
    """Typed checkout configuration — top-level camelCase fields."""

    deliveryEnabled = serializers.BooleanField(source="delivery_enabled", read_only=True)
    pickupEnabled = serializers.BooleanField(source="pickup_enabled", read_only=True)
    tableOrderingEnabled = serializers.BooleanField(source="table_ordering_enabled", read_only=True)
    orderingEnabled = serializers.BooleanField(source="ordering_enabled", read_only=True)
    deliveryRadius = serializers.IntegerField(source="delivery_radius_km", read_only=True, allow_null=True)
    minimumOrder = serializers.DecimalField(
        source="minimum_order_amount", max_digits=10, decimal_places=2,
        read_only=True, allow_null=True,
    )
    defaultOrderType = serializers.CharField(source="default_order_type", read_only=True, allow_null=True)
    cashPaymentEnabled = serializers.BooleanField(source="cash_payment_enabled", read_only=True)
    cardPaymentEnabled = serializers.BooleanField(source="card_payment_enabled", read_only=True)
    onlinePaymentEnabled = serializers.BooleanField(source="online_payment_enabled", read_only=True)
    walletPaymentEnabled = serializers.BooleanField(source="wallet_payment_enabled", read_only=True)
    cashOnDeliveryEnabled = serializers.BooleanField(source="cash_on_delivery_enabled", read_only=True)
    defaultPaymentMethod = serializers.CharField(source="default_payment_method", read_only=True, allow_null=True)
    sameDayDeliveryEnabled = serializers.BooleanField(source="same_day_delivery_enabled", read_only=True)
    scheduledDeliveryEnabled = serializers.BooleanField(source="scheduled_delivery_enabled", read_only=True)
    contactlessDeliveryEnabled = serializers.BooleanField(source="contactless_delivery_enabled", read_only=True)
    marketplaceVisible = serializers.BooleanField(source="marketplace_visible", read_only=True)
    reservationsEnabled = serializers.BooleanField(source="reservations_enabled", read_only=True)
    maxCapacity = serializers.IntegerField(source="max_capacity", read_only=True, allow_null=True)


# ---------------------------------------------------------------------------
# Branch (DTO or ORM)
# ---------------------------------------------------------------------------

class BranchResponseSerializer(BranchCheckoutResponseMixin, serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenantId = serializers.SerializerMethodField()
    tenant = serializers.SerializerMethodField()
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    status = serializers.SerializerMethodField()
    type = serializers.CharField(read_only=True)
    location = BranchLocationResponseSerializer(source="*", read_only=True)
    contact = BranchContactResponseSerializer(source="*", read_only=True)
    managerId = serializers.SerializerMethodField()
    businessHours = serializers.SerializerMethodField()
    checkout = CheckoutConfigurationSerializer(source="*", read_only=True)
    settings = serializers.JSONField(read_only=True)
    image = serializers.SerializerMethodField()
    coverImage = serializers.SerializerMethodField()
    heroImage = serializers.SerializerMethodField()
    isDefault = serializers.BooleanField(source="is_default", read_only=True)
    cuisines = serializers.ListField(child=serializers.CharField(), read_only=True)
    amenities = serializers.ListField(child=serializers.CharField(), read_only=True)
    timeZone = serializers.CharField(source="time_zone", read_only=True)
    currency = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    metadata = serializers.JSONField(read_only=True)

    def get_tenantId(self, obj):
        return getattr(obj, "tenant_id", None)

    def get_tenant(self, obj):
        summary = build_tenant_summary(obj)
        if summary is None:
            tenant = getattr(obj, "tenant", None)
            summary = build_tenant_summary(tenant)
        if summary is None:
            return None
        return TenantSummarySerializer(summary).data

    def get_managerId(self, obj):
        return getattr(obj, "manager_id", None)

    def get_businessHours(self, obj):
        hours = getattr(obj, "working_hours", [])
        if not isinstance(hours, list):
            hours = list(hours.all())
        return BranchBusinessHoursResponseSerializer(hours, many=True).data

    def get_image(self, obj):
        return _media_url(obj, "image", "image_url")

    def get_coverImage(self, obj):
        return _media_url(obj, "cover_image", "cover_image_url")

    def get_heroImage(self, obj):
        return _media_url(obj, "hero_image", "hero_image_url")

    def get_status(self, obj) -> str:
        if not obj.is_active:
            return "inactive"
        return obj.status


class TenantResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    owner_id = serializers.SerializerMethodField()
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    tax_percentage = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)
    serviceChargePercentage = serializers.DecimalField(
        source="service_charge_percentage",
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )
    image = serializers.SerializerMethodField()
    discoverAvatar = serializers.SerializerMethodField()
    discoverCover = serializers.SerializerMethodField()
    heroImage = serializers.SerializerMethodField()
    business_types = BusinessTypesField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    settings = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def get_settings(self, obj):
        raw = getattr(obj, "settings", None) or {}
        if not isinstance(raw, dict):
            raw = {}
        if self.context.get("public_settings"):
            return project_public_tenant_settings(raw)
        return project_owner_tenant_settings(raw)

    def get_owner_id(self, obj):
        owner_user_id = getattr(obj, "owner_user_id", None)
        if owner_user_id is not None:
            return owner_user_id
        owner = getattr(obj, "owner", None)
        return getattr(owner, "user_id", None) if owner is not None else None

    def get_image(self, obj):
        return _media_url(obj, "image", "image_url")

    def get_discoverAvatar(self, obj):
        return _media_url(obj, "discover_avatar", "discover_avatar_url")

    def get_discoverCover(self, obj):
        return _media_url(obj, "discover_cover", "discover_cover_url")

    def get_heroImage(self, obj):
        return _media_url(obj, "hero_image", "hero_image_url")


class PublicTenantResponseSerializer(serializers.Serializer):
    """Public discover-page contract for GET /api/tenants/."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    image = serializers.SerializerMethodField()
    discoverAvatar = serializers.SerializerMethodField()
    discoverCover = serializers.SerializerMethodField()
    heroImage = serializers.SerializerMethodField()
    business_types = BusinessTypesField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    tax_percentage = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)
    settings = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def get_settings(self, obj):
        return project_public_tenant_settings(getattr(obj, "settings", None) or {})

    def get_image(self, obj):
        return _media_url(obj, "image", "image_url")

    def get_discoverAvatar(self, obj):
        return _media_url(obj, "discover_avatar", "discover_avatar_url")

    def get_discoverCover(self, obj):
        return _media_url(obj, "discover_cover", "discover_cover_url")

    def get_heroImage(self, obj):
        return _media_url(obj, "hero_image", "hero_image_url")
