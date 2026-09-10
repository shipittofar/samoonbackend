from rest_framework import serializers

from accounts.models import User


class ConsoleCustomerResponseSerializer(serializers.ModelSerializer):
    """Console customer identity plus scoped activity counts.

    Branch membership is omitted: the list is already tenant- or branch-scoped,
    and embedding branches would require extra queries without a current UI
    contract for that payload.
    """

    orders_count = serializers.IntegerField(read_only=True)
    reservations_count = serializers.IntegerField(read_only=True)
    last_activity_at = serializers.DateTimeField(read_only=True, allow_null=True)
    phone_number = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "orders_count",
            "reservations_count",
            "last_activity_at",
        ]

    def get_phone_number(self, obj):
        return obj.phone_number or None
