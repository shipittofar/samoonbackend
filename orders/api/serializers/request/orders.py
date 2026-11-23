# orders/api/serializers/request.py
from rest_framework import serializers

from orders.models import OrderStatus, OrderType, PaymentMethod


class OrderItemRequestSerializer(serializers.Serializer):
    menu_item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    extras = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
    )


class DeliveryAddressRequestSerializer(serializers.Serializer):
    """
    Checkout delivery address payload.

    Accept either:
    - `address_id` (UUID or legacy integer string) referencing the user address book, OR
    - inline address fields for guest / one-off delivery.

    If both are supplied, `address_id` wins. Override fields (delivery_notes,
    building_number, unit, floor) may be supplied alongside address_id.
    """

    address_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    # Legacy inline field names (backward compatible)
    label = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    street = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    state = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    zip = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)

    # New inline field names
    title = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    company = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    country_code = serializers.CharField(max_length=5, required=False, allow_blank=True, default="")
    country = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    province = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    building_number = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    floor = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    postal_code = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    delivery_notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        raw_id = attrs.get("address_id")
        if raw_id:
            attrs["address_id"] = self._normalize_address_id(raw_id)
            return attrs

        street = attrs.get("street")
        city = attrs.get("city")
        if not (street and city):
            raise serializers.ValidationError(
                "Provide either 'address_id' or inline address fields including street and city."
            )
        return attrs

    @staticmethod
    def _normalize_address_id(raw_id: str):
        value = str(raw_id).strip()
        if value.isdigit():
            return int(value)
        return value


class OrderRequestSerializerBase(serializers.Serializer):
    """
    Shared shape for both order creation and order editing (reorder).
    """

    branch_id = serializers.UUIDField()
    items = OrderItemRequestSerializer(many=True)
    order_type = serializers.ChoiceField(choices=OrderType.choices)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    # The currency the customer viewed prices in (recorded on the order with
    # the rates used; the order is still charged in the business currency).
    display_currency = serializers.CharField(max_length=10, required=False, allow_blank=True)
    delivery_address = DeliveryAddressRequestSerializer(
        required=False, allow_null=True
    )
    table_number = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    discount_code = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Order must contain at least one item.")
        return items

    def validate(self, attrs):
        order_type = attrs.get("order_type")

        if order_type == OrderType.DELIVERY and not attrs.get("delivery_address"):
            raise serializers.ValidationError(
                {"delivery_address": "Required when order_type is 'delivery'."}
            )

        if order_type == OrderType.DINE_IN and not attrs.get("table_number"):
            raise serializers.ValidationError(
                {"table_number": "Required when order_type is 'dine_in'."}
            )

        return attrs


class CreateOrderRequestSerializer(OrderRequestSerializerBase):
    pass


class UpdateOrderRequestSerializer(OrderRequestSerializerBase):
    pass


class ValidateDiscountRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    discount_code = serializers.CharField(max_length=50)
    subtotal = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class UpdateOrderStatusRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
