from rest_framework import serializers
import json

from tenants.api.serializers.fields import BusinessTypesField
from tenants.models import (
    TenantStatus,
    WorkingHour,
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
    owner = serializers.UUIDField()

    name = serializers.CharField(max_length=255)

    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=30,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    city = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )

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

    tax_percentage = serializers.DecimalField(
        max_digits=4, decimal_places=2,
        required=False, default=0,
        min_value=0, max_value=100,
    )

    image = serializers.ImageField(required=False, allow_null=True)

    business_types = BusinessTypesField(required=False, default=list)
    status = serializers.ChoiceField(
        choices=TenantStatus.choices,
        required=False,
        default=TenantStatus.ACTIVE,
    )
    is_active = serializers.BooleanField(required=False, default=True)

    working_hours = WorkingHourSerializer(many=True, required=False)

    def validate_owner(self, value):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Owner user does not exist.")
        return value

    def validate_working_hours(self, value):
        days = [wh["day"] for wh in value]
        if len(days) != len(set(days)):
            raise serializers.ValidationError(
                "Duplicate day found in working_hours."
            )
        return value

    def to_internal_value(self, data):
        # QueryDict رو به dict معمولی تبدیل کن تا DRF دیگه سراغ html.parse_html_list نره
        data = data.dict() if hasattr(data, "dict") else dict(data)

        wh = data.get("working_hours")
        if isinstance(wh, str):
            try:
                data["working_hours"] = json.loads(wh)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"working_hours": "Invalid JSON format."}
                )

        return super().to_internal_value(data)


class TenantUpdateSerializer(serializers.Serializer):
    owner = serializers.UUIDField()

    name = serializers.CharField(max_length=255)

    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=30,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    city = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )

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

    tax_percentage = serializers.DecimalField(
        max_digits=4, decimal_places=2,
        required=False, default=0,
        min_value=0, max_value=100,
    )

    image = serializers.ImageField(required=False, allow_null=True)

    business_types = BusinessTypesField(required=False, default=list)
    status = serializers.ChoiceField(
        choices=TenantStatus.choices,
        required=False,
        default=TenantStatus.ACTIVE,
    )
    is_active = serializers.BooleanField(required=False, default=True)

    working_hours = WorkingHourSerializer(many=True, required=False)

    def validate_owner(self, value):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Owner user does not exist.")
        return value

    def validate_working_hours(self, value):
        days = [wh["day"] for wh in value]
        if len(days) != len(set(days)):
            raise serializers.ValidationError(
                "Duplicate day found in working_hours."
            )
        return value

    def to_internal_value(self, data):
        # QueryDict رو به dict معمولی تبدیل کن تا DRF دیگه سراغ html.parse_html_list نره
        data = data.dict() if hasattr(data, "dict") else dict(data)

        wh = data.get("working_hours")
        if isinstance(wh, str):
            try:
                data["working_hours"] = json.loads(wh)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"working_hours": "Invalid JSON format."}
                )

        return super().to_internal_value(data)