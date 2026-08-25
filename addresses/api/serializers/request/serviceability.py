from rest_framework import serializers


class CheckServiceabilityRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    address_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    delivery_address = serializers.DictField(required=False, allow_null=True)

    def validate(self, attrs):
        has_id = bool(attrs.get("address_id"))
        has_inline = bool(attrs.get("delivery_address"))
        if not has_id and not has_inline:
            raise serializers.ValidationError(
                "Provide either address_id or delivery_address."
            )
        return attrs
