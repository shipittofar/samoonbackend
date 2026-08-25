from rest_framework import serializers

from menu.models import MenuCategory


class MenuCategoryOutputSerializer(serializers.ModelSerializer):
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
            "created_at",
            "updated_at",
        ]