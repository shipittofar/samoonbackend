from rest_framework import serializers

from accounts.models import Favorite
from menu.models import MenuItem
from menu.utils.item_compat import compute_discounted_price


class FavoriteSyncStateSerializer(serializers.Serializer):
    version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    total_count = serializers.IntegerField()
    branch_id = serializers.UUIDField(allow_null=True, required=False)


class FavoriteTenantEmbedSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)


class FavoriteBranchEmbedSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class FavoriteMenuItemEmbedSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="branch.tenant_id", read_only=True)
    discounted_price = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model = MenuItem
        fields = [
            "id",
            "tenant_id",
            "branch_id",
            "category_id",
            "name",
            "slug",
            "description",
            "price",
            "discount",
            "discounted_price",
            "image",
            "is_active",
            "available",
            "is_deleted",
        ]

    def get_discounted_price(self, obj):
        return compute_discounted_price(obj.price, obj.discount)

    def get_image(self, obj):
        return obj.image.url if obj.image else ""

    def get_description(self, obj):
        return obj.description or ""

    def get_is_deleted(self, obj):
        return obj.deleted_at is not None


class FavoriteResponseSerializer(serializers.ModelSerializer):
    menu_item_id = serializers.UUIDField(source="menu_item.id", read_only=True)
    branch_id = serializers.UUIDField(source="menu_item.branch_id", read_only=True)
    tenant_id = serializers.UUIDField(source="menu_item.branch.tenant_id", read_only=True)
    tenant = FavoriteTenantEmbedSerializer(source="menu_item.branch.tenant", read_only=True)
    branch = FavoriteBranchEmbedSerializer(source="menu_item.branch", read_only=True)
    favorited_at = serializers.DateTimeField(source="created_at", read_only=True)
    menu_item = FavoriteMenuItemEmbedSerializer(read_only=True)

    class Meta:
        model = Favorite
        fields = [
            "id",
            "menu_item_id",
            "branch_id",
            "tenant_id",
            "tenant",
            "branch",
            "favorited_at",
            "menu_item",
        ]


class FavoriteMutationResponseSerializer(serializers.Serializer):
    favorite = FavoriteResponseSerializer(allow_null=True)
    removed = serializers.BooleanField(required=False)
    menu_item_id = serializers.UUIDField(required=False)
    sync = FavoriteSyncStateSerializer()
    created = serializers.BooleanField(required=False)


class FavoriteSyncResponseSerializer(serializers.Serializer):
    sync = FavoriteSyncStateSerializer()
    favorite_ids = serializers.ListField(child=serializers.UUIDField())


class FavoriteListResponseSerializer(serializers.Serializer):
    sync = FavoriteSyncStateSerializer()
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = FavoriteResponseSerializer(many=True)
