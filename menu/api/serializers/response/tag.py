from rest_framework import serializers

from menu.models import Tag


class TagOutputSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = [
            "id",
            "name",
            "slug",
            "icon",
            "image",
            "color",
        ]

    def get_image(self, obj):
        return obj.image.url if obj.image else ""


class TagManagementOutputSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = [
            "id",
            "branch_id",
            "name",
            "slug",
            "description",
            "icon",
            "image",
            "color",
            "is_active",
            "display_order",
            "created_at",
            "updated_at",
        ]

    def get_image(self, obj):
        return obj.image.url if obj.image else ""


class AvailableTagOutputSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Tag
        fields = [
            "id",
            "name",
            "slug",
            "icon",
            "image",
            "color",
            "item_count",
        ]

    def get_image(self, obj):
        return obj.image.url if obj.image else ""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_item_count", True):
            data.pop("item_count", None)
        return data
