from rest_framework import serializers

from menu.models import MenuItem, Extra, MenuCategory
from menu.api.serializers.response.tag import TagOutputSerializer
from menu.utils.item_compat import (
    build_nutritional_info,
    compute_discounted_price,
    compute_is_new,
    compute_rating,
    compute_rating_count,
    serialize_materialized_extras,
)


class MenuItemCategoryEmbedSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuCategory
        fields = ["id", "branch_id", "name", "slug", "sort_order"]


class MenuItemOutputSerializer(serializers.ModelSerializer):
    """
    Canonical MenuItem response shape.

    Exposes persisted fields and computed frontend-compat values
    (discounted_price, rating, extras, …). ``available`` and ``is_active``
    are independent model fields with separate semantics.
    """

    tags = TagOutputSerializer(many=True, read_only=True)
    extra_group_ids = serializers.SerializerMethodField()
    discounted_price = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()
    is_new = serializers.SerializerMethodField()
    extras = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    allergens = serializers.SerializerMethodField()
    nutritional_info = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    preparation_time = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    prices = serializers.SerializerMethodField()

    class Meta:
        model = MenuItem
        fields = [
            "id",
            "branch_id",
            "category_id",
            "category",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "prices",
            "discount",
            "discounted_price",
            "image",
            "images",
            "calories",
            "preparation_time",
            "rating",
            "rating_count",
            "is_active",
            "available",
            "is_popular",
            "is_featured",
            "is_new",
            "tags",
            "extras",
            "extra_group_ids",
            "allergens",
            "nutritional_info",
            "created_at",
            "updated_at",
        ]

    def get_extra_group_ids(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get(
            "item_extra_groups"
        )
        if prefetched is not None:
            return [str(link.extra_group_id) for link in prefetched]
        return [
            str(group_id)
            for group_id in obj.item_extra_groups.values_list(
                "extra_group_id", flat=True
            )
        ]

    def get_discounted_price(self, obj):
        discounted = compute_discounted_price(obj.price, obj.discount)
        if discounted is None:
            return None
        return discounted

    def get_rating(self, obj):
        return compute_rating()

    def get_rating_count(self, obj):
        return compute_rating_count()

    def get_is_new(self, obj):
        return compute_is_new(obj.created_at)

    def get_extras(self, obj):
        return serialize_materialized_extras(obj)

    def get_images(self, obj):
        if not obj.image:
            return []
        return [obj.image.url]

    def get_allergens(self, obj):
        return []

    def get_nutritional_info(self, obj):
        return build_nutritional_info(obj.calories)

    def get_category(self, obj):
        category = getattr(obj, "category", None)
        if category is None:
            return None
        return MenuItemCategoryEmbedSerializer(category).data

    def get_preparation_time(self, obj):
        return obj.preparation_time if obj.preparation_time is not None else 0

    def get_image(self, obj):
        return obj.image.url if obj.image else ""

    def get_description(self, obj):
        return obj.description or ""

    def get_currency(self, obj):
        """The currency ``price`` is in: the branch's (platform base if unset)."""
        from currencies.services import DEFAULT_BASE, base_code

        branch = getattr(obj, "branch", None)
        if branch is None:
            return DEFAULT_BASE  # no branch loaded: no database lookup
        return getattr(branch, "currency", "") or base_code()

    def get_prices(self, obj):
        """The owner's own prices in other currencies, e.g. {"USD": "3.00"}."""
        return dict(getattr(obj, "prices", None) or {})


class ExtraOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Extra
        fields = [
            "id",
            "branch_id",
            "group_id",
            "name",
            "description",
            "price",
            "available",
            "order",
            "created_at",
        ]


class MenuItemExtraOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    extra_id = serializers.UUIDField()
    name = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    available = serializers.BooleanField()
    price_override = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
