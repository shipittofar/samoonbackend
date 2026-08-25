from rest_framework import serializers


class TagFilterQuerySerializer(serializers.Serializer):
    tags = serializers.CharField(
        required=False,
        help_text="Comma-separated branch tag IDs, e.g. 1 or 1,3,7",
    )


class MenuItemSearchQuerySerializer(TagFilterQuerySerializer):
    q = serializers.CharField(required=False, help_text="Search query")


class ItemPriceQuerySerializer(TagFilterQuerySerializer):
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    max_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    order = serializers.ChoiceField(choices=["asc", "desc"], required=False, default="asc")


class ItemPreparationTimeQuerySerializer(TagFilterQuerySerializer):
    min_preparation_time = serializers.IntegerField(min_value=0, required=False)
    max_preparation_time = serializers.IntegerField(min_value=0, required=False)
    order = serializers.ChoiceField(choices=["asc", "desc"], required=False, default="asc")


class ItemCalorieQuerySerializer(TagFilterQuerySerializer):
    min_calories = serializers.IntegerField(min_value=0, required=False)
    max_calories = serializers.IntegerField(min_value=0, required=False)
    order = serializers.ChoiceField(choices=["asc", "desc"], required=False, default="asc")


class ItemDiscountQuerySerializer(TagFilterQuerySerializer):
    has_discount = serializers.BooleanField(required=False)
    min_discount = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    max_discount = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    order = serializers.ChoiceField(choices=["asc", "desc"], required=False, default="asc")