from rest_framework import serializers

from tenants.models import Tenant, WorkingHour


class WorkingHourResponseSerializer(serializers.ModelSerializer):
    day_display = serializers.CharField(source="get_day_display", read_only=True)

    class Meta:
        model = WorkingHour
        fields = (
            "day",
            "day_display",
            "open_time",
            "close_time",
            "is_closed",
        )


class TenantCreateResponseSerializer(serializers.ModelSerializer):
    working_hours = WorkingHourResponseSerializer(many=True, read_only=True)

    class Meta:
        model = Tenant
        fields = (
            "id",
            "owner",
            "name",
            "slug",
            "phone",
            "address",
            "city",
            "latitude",
            "longitude",
            "tax_percentage",
            "image",
            "business_types",
            "status",
            "is_active",
            "working_hours",
        )


class TenantRetrieveResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    owner = serializers.UUIDField(source="owner_id")
    name = serializers.CharField()
    slug = serializers.CharField()
    phone = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, allow_null=True
    )
    tax_percentage = serializers.DecimalField(max_digits=4, decimal_places=2)
    image = serializers.ImageField(allow_null=True, required=False)
    business_types = serializers.ListField(child=serializers.CharField())
    status = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    working_hours = WorkingHourResponseSerializer(many=True)