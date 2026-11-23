# orders/api/serializers/response.py
from rest_framework import serializers

from orders.models import Order, OrderDeliveryAddress, OrderItem, OrderItemExtra
from tenants.api.serializers.response.tenant_summary import TenantSummarySerializer


class OrderItemExtraResponseSerializer(serializers.ModelSerializer):
    extra_id = serializers.UUIDField(source="extra.id", read_only=True)
    name = serializers.CharField(source="extra.name", read_only=True)

    class Meta:
        model = OrderItemExtra
        fields = ["extra_id", "name", "price"]


class OrderItemResponseSerializer(serializers.ModelSerializer):
    """Line-item snapshot; menu_item_id is the public MenuItem UUID."""

    menu_item_id = serializers.UUIDField(source="menu_item.id", read_only=True)
    extras = OrderItemExtraResponseSerializer(many=True, read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "menu_item_id",
            "name",
            "image",
            "quantity",
            "unit_price",
            "notes",
            "extras",
            "total_price",
        ]


class DeliveryAddressResponseSerializer(serializers.ModelSerializer):
    """
    Backward-compatible delivery address shape for order responses.
    Maps immutable snapshot fields to the legacy frontend contract.
    """

    id = serializers.UUIDField(read_only=True)
    label = serializers.SerializerMethodField()
    state = serializers.CharField(source="province")
    zip = serializers.CharField(source="postal_code")
    lat = serializers.FloatField(source="latitude", allow_null=True)
    lng = serializers.FloatField(source="longitude", allow_null=True)
    formatted_address = serializers.CharField(read_only=True)

    class Meta:
        model = OrderDeliveryAddress
        fields = [
            "id", "label", "street", "city", "state", "zip", "lat", "lng",
            "formatted_address", "floor", "building_number", "unit",
            "delivery_zone", "branch_id", "verification_status",
            "distance_km", "delivery_fee", "estimated_delivery_time", "calculated_at",
        ]

    def get_label(self, obj) -> str:
        return obj.title or obj.label or ""


class OrderResponseSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_slug = serializers.CharField(source="branch.slug", read_only=True)
    tenant_id = serializers.UUIDField(source="branch.tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="branch.tenant.name", read_only=True)
    tenant_slug = serializers.CharField(source="branch.tenant.slug", read_only=True)
    tenant_is_active = serializers.BooleanField(
        source="branch.tenant.is_active", read_only=True
    )
    tenant_status = serializers.CharField(source="branch.tenant.status", read_only=True)
    tenant = serializers.SerializerMethodField()
    items = OrderItemResponseSerializer(many=True, read_only=True)
    delivery_address = DeliveryAddressResponseSerializer(read_only=True)

    def get_tenant(self, obj):
        tenant = getattr(getattr(obj, "branch", None), "tenant", None)
        if tenant is None:
            return None
        return TenantSummarySerializer(
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "is_active": tenant.is_active,
                "status": tenant.status,
            }
        ).data

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "branch_id",
            "branch_name",
            "branch_slug",
            "tenant_id",
            "tenant_name",
            "tenant_slug",
            "tenant_is_active",
            "tenant_status",
            "tenant",
            "order_type",
            "status",
            "payment_method",
            "payment_status",
            "table_number",
            "discount_code",
            "subtotal",
            "discount_amount",
            "tax",
            "service_charge",
            "total",
            "currency",
            "display_currency",
            "display_total",
            "exchange_rates",
            "notes",
            "items",
            "delivery_address",
            "created_at",
            "updated_at",
        ]


class OrderListItemLightweightResponseSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "branch_id",
            "branch_name",
            "order_type",
            "status",
            "payment_status",
            "total",
            "currency",
            "display_currency",
            "display_total",
            "created_at",
        ]


class OrderListItemResponseSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    tenant_id = serializers.UUIDField(source="branch.tenant.id", read_only=True)
    tenant_is_active = serializers.BooleanField(
        source="branch.tenant.is_active", read_only=True
    )
    tenant_status = serializers.CharField(source="branch.tenant.status", read_only=True)
    tenant = serializers.SerializerMethodField()
    items = OrderItemResponseSerializer(many=True, read_only=True)

    def get_tenant(self, obj):
        tenant = getattr(getattr(obj, "branch", None), "tenant", None)
        if tenant is None:
            return None
        return TenantSummarySerializer(
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "is_active": tenant.is_active,
                "status": tenant.status,
            }
        ).data

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "branch_id",
            "branch_name",
            "tenant_id",
            "tenant_is_active",
            "tenant_status",
            "tenant",
            "order_type",
            "status",
            "payment_status",
            "total",
            "currency",
            "display_currency",
            "display_total",
            "created_at",
            "items",
        ]


class ValidateDiscountResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    discount_code = serializers.CharField()
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class PendingCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
