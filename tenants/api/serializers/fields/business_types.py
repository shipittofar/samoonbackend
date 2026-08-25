import json

from rest_framework import serializers

from tenants.constants.business_type import (
    normalize_business_types,
    validate_business_types,
)


class BusinessTypesField(serializers.ListField):
    child = serializers.CharField()

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                raise serializers.ValidationError("business_types must be a JSON array.")
        values = super().to_internal_value(data)
        normalized = normalize_business_types(values)
        try:
            return validate_business_types(normalized)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def to_representation(self, value):
        if value is None:
            return []
        return list(value)


class BusinessTypesCamelCaseField(BusinessTypesField):
    """Accepts `businessTypes` (camelCase) on input; same validation rules."""

    def get_value(self, dictionary):
        if "businessTypes" in dictionary:
            return dictionary.get("businessTypes")
        return dictionary.get("business_types")
