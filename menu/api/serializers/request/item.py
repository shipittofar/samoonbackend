from rest_framework import serializers


# insert one obj
class MenuItemInputSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    category_id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(default="", allow_blank=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0, min_value=0
    )
    image = serializers.ImageField(required=False, allow_null=True)
    image_asset_id = serializers.UUIDField(required=False, allow_null=True)
    calories = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    preparation_time = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    is_active = serializers.BooleanField(default=True)
    available = serializers.BooleanField(default=True)
    is_popular = serializers.BooleanField(default=False)
    is_featured = serializers.BooleanField(default=False)
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class MenuItemUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    discount = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0
    )
    image = serializers.ImageField(required=False, allow_null=True)
    image_asset_id = serializers.UUIDField(required=False, allow_null=True)
    calories = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    preparation_time = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    is_active = serializers.BooleanField(required=False)
    available = serializers.BooleanField(required=False)
    is_popular = serializers.BooleanField(required=False)
    is_featured = serializers.BooleanField(required=False)

    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    extra_group_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False
    )


# insert bulk obj
class MenuItemBulkCreateInputSerializer(serializers.Serializer):
    items = MenuItemInputSerializer(many=True, allow_empty=False, max_length=500)


class ExtraInputSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    group_id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    available = serializers.BooleanField(default=True)
    order = serializers.IntegerField(default=0, min_value=0)


class ExtraUpdateSerializer(serializers.Serializer):
    group_id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    available = serializers.BooleanField(required=False)
    order = serializers.IntegerField(min_value=0, required=False)


class MenuItemExtraInputSerializer(serializers.Serializer):
    extra_id = serializers.UUIDField()
    price_override = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class MenuItemExtraUpdateSerializer(serializers.Serializer):
    price_override = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class MenuItemAssignExtraGroupsSerializer(serializers.Serializer):
    extra_group_ids = serializers.ListField(
        child=serializers.UUIDField(), required=True
    )
