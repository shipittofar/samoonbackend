from rest_framework import serializers


class FavoriteCreateRequestSerializer(serializers.Serializer):
    menu_item_id = serializers.UUIDField()
