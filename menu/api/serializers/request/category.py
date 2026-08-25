from rest_framework import serializers


# insert one obj
class MenuCategoryInputSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    image = serializers.ImageField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(default=0, min_value=0)


class MenuCategoryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    image = serializers.ImageField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(min_value=0, required=False)


# insert bulk obj
class MenuCategoryBulkCreateInputSerializer(serializers.Serializer):
    categories = MenuCategoryInputSerializer(many=True, allow_empty=False, max_length=500)