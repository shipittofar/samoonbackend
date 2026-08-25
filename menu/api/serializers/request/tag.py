import re

from rest_framework import serializers

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class TagInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    slug = serializers.SlugField(max_length=60, required=False, allow_blank=True)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    icon = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )
    image = serializers.ImageField(required=False, allow_null=True)
    color = serializers.CharField(
        max_length=7, required=False, allow_blank=True, default=""
    )
    is_active = serializers.BooleanField(default=True)
    display_order = serializers.IntegerField(default=0, min_value=0)

    def validate_icon(self, value):
        if value and len(value) > 16:
            raise serializers.ValidationError("Icon must be at most 16 characters.")
        return value

    def validate_color(self, value):
        if value and not HEX_COLOR_PATTERN.match(value):
            raise serializers.ValidationError(
                "Color must be a valid HEX value like #2ecc71."
            )
        return value


class TagUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50, required=False)
    slug = serializers.SlugField(max_length=60, required=False, allow_blank=True)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    icon = serializers.CharField(max_length=16, required=False, allow_blank=True)
    image = serializers.ImageField(required=False, allow_null=True)
    color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    display_order = serializers.IntegerField(min_value=0, required=False)

    def validate_icon(self, value):
        if value and len(value) > 16:
            raise serializers.ValidationError("Icon must be at most 16 characters.")
        return value

    def validate_color(self, value):
        if value and not HEX_COLOR_PATTERN.match(value):
            raise serializers.ValidationError(
                "Color must be a valid HEX value like #2ecc71."
            )
        return value


class AvailableTagQuerySerializer(serializers.Serializer):
    include_item_count = serializers.BooleanField(default=True)
