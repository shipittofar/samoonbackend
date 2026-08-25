from rest_framework import serializers

from menu.models import MenuCategory
from menu.api.serializers.response.item import MenuItemOutputSerializer

__all__ = [
    "MenuCategoryWithItemsOutputSerializer",
    "MenuItemOutputSerializer",
]


class MenuCategoryWithItemsOutputSerializer(serializers.ModelSerializer):
    items = MenuItemOutputSerializer(many=True, read_only=True)

    class Meta:
        model = MenuCategory
        fields = [
            "id",
            "branch_id",
            "name",
            "slug",
            "description",
            "image",
            "sort_order",
            "items",
            "created_at",
            "updated_at",
        ]
