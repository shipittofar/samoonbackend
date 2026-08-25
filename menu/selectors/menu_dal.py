from django.db.models import Prefetch, Q

from core.cache import cache_get, cache_set, CacheKeys, CacheTTL
from menu.models import MenuCategory, MenuItem
from menu.selectors.item_visibility import queryset_public_active_items
from menu.utils.item_compat import compute_rating, compute_rating_count

BRANCH_ITEMS_TTL = CacheTTL.MENU_BRANCH_ITEMS_ALL
CATEGORIES_WITH_ITEMS_TTL = CacheTTL.MENU_BRANCH_CATEGORIES_WITH_ITEMS

_ITEM_PREFETCH = (
    "tags",
    "item_extras__extra",
    "item_extra_groups",
    "category",
)


class MenuDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_branch_items_cache(branch_id) -> list[MenuItem]:
        """
        Loads every MenuItem of a branch once and caches it as a single
        list. All filter/sort endpoints (price, prep time, calories,
        discount, popular, featured, active, counts) read from this one
        cached list and filter/sort in Python instead of hitting the
        database with a different query per parameter combination — that
        would produce unbounded cache-key cardinality.
        """
        data = list(
            MenuItem.objects.filter(branch_id=branch_id).prefetch_related(
                *_ITEM_PREFETCH
            )
        )
        key = CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=branch_id)
        cache_set(key, data, BRANCH_ITEMS_TTL)
        return data

    @staticmethod
    def _get_branch_items(branch_id) -> list[MenuItem]:
        key = CacheKeys.MENU_BRANCH_ITEMS_ALL.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return MenuDataAccessLayer._refresh_branch_items_cache(branch_id)

    @staticmethod
    def invalidate_branch_items_cache(branch_id) -> None:
        """Call after any create/update/delete/bulk_create of a MenuItem in this branch."""
        MenuDataAccessLayer._refresh_branch_items_cache(branch_id)

    @staticmethod
    def _refresh_categories_with_items_cache(branch_id) -> list[MenuCategory]:
        active_items_qs = MenuItem.objects.filter(is_active=True).prefetch_related(
            *_ITEM_PREFETCH
        )
        data = list(
            MenuCategory.objects.filter(branch_id=branch_id).prefetch_related(
                Prefetch("items", queryset=active_items_qs),
            )
        )
        key = CacheKeys.MENU_BRANCH_CATEGORIES_WITH_ITEMS.format(branch_id=branch_id)
        cache_set(key, data, CATEGORIES_WITH_ITEMS_TTL)
        return data

    @staticmethod
    def invalidate_categories_with_items_cache(branch_id) -> None:
        """Call after any create/update/delete of a MenuCategory or MenuItem in this branch."""
        MenuDataAccessLayer._refresh_categories_with_items_cache(branch_id)

    # ---------- reads (cached) ----------

    @staticmethod
    def _public_items_queryset(
        branch_id,
        *,
        tags=None,
        is_popular=None,
        is_featured=None,
        exclude_item_id=None,
        category_id=None,
    ):
        qs = queryset_public_active_items(branch_id).prefetch_related(
            *_ITEM_PREFETCH
        )
        if tags:
            qs = qs.filter(tags__id__in=tags).distinct()
        if is_popular is not None:
            qs = qs.filter(is_popular=is_popular)
        if is_featured is not None:
            qs = qs.filter(is_featured=is_featured)
        if exclude_item_id is not None:
            qs = qs.exclude(id=exclude_item_id)
        if category_id is not None:
            qs = qs.filter(category_id=category_id)
        return qs

    @staticmethod
    def _fetch_categories_with_items(branch_id, *, tags=None) -> list[MenuCategory]:
        active_items_qs = queryset_public_active_items(branch_id).prefetch_related(
            *_ITEM_PREFETCH
        )
        if tags:
            active_items_qs = active_items_qs.filter(tags__id__in=tags).distinct()
        return list(
            MenuCategory.objects.filter(branch_id=branch_id).prefetch_related(
                Prefetch("items", queryset=active_items_qs),
            )
        )

    @staticmethod
    def get_categories_with_items(branch_id, *, tags=None) -> list[MenuCategory]:
        if tags:
            return MenuDataAccessLayer._fetch_categories_with_items(
                branch_id, tags=tags
            )
        key = CacheKeys.MENU_BRANCH_CATEGORIES_WITH_ITEMS.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return MenuDataAccessLayer._refresh_categories_with_items_cache(branch_id)

    @staticmethod
    def _get_public_active_items(branch_id) -> list[MenuItem]:
        """
        Published items for public browse endpoints.

        Always reads ``is_active`` from the database so visibility never
        depends on ``available`` and is not affected by stale branch caches.
        """
        return list(
            queryset_public_active_items(branch_id).prefetch_related(
                *_ITEM_PREFETCH
            )
        )

    @staticmethod
    def get_popular_items(branch_id, *, tags=None) -> list[MenuItem]:
        if tags:
            return list(
                MenuDataAccessLayer._public_items_queryset(
                    branch_id, tags=tags, is_popular=True
                ).order_by("name")
            )
        return [
            item
            for item in MenuDataAccessLayer._get_public_active_items(branch_id)
            if item.is_popular
        ]

    @staticmethod
    def get_featured_items(branch_id, *, tags=None) -> list[MenuItem]:
        if tags:
            return list(
                MenuDataAccessLayer._public_items_queryset(
                    branch_id, tags=tags, is_featured=True
                ).order_by("name")
            )
        return [
            item
            for item in MenuDataAccessLayer._get_public_active_items(branch_id)
            if item.is_featured
        ]

    @staticmethod
    def get_active_items(branch_id, *, tags=None) -> list[MenuItem]:
        if tags:
            return list(
                MenuDataAccessLayer._public_items_queryset(branch_id, tags=tags).order_by(
                    "name"
                )
            )
        return MenuDataAccessLayer._get_public_active_items(branch_id)

    @staticmethod
    def get_items_by_price(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ) -> list[MenuItem]:
        if tags:
            qs = MenuDataAccessLayer._public_items_queryset(branch_id, tags=tags)
            if min_value is not None:
                qs = qs.filter(price__gte=min_value)
            if max_value is not None:
                qs = qs.filter(price__lte=max_value)
            order_field = "-price" if order == "desc" else "price"
            return list(qs.order_by(order_field))
        items = MenuDataAccessLayer._get_public_active_items(branch_id)
        if min_value is not None:
            items = [i for i in items if i.price >= min_value]
        if max_value is not None:
            items = [i for i in items if i.price <= max_value]
        return sorted(items, key=lambda i: i.price, reverse=(order == "desc"))

    @staticmethod
    def get_items_by_preparation_time(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ) -> list[MenuItem]:
        if tags:
            qs = MenuDataAccessLayer._public_items_queryset(
                branch_id, tags=tags
            ).filter(preparation_time__isnull=False)
            if min_value is not None:
                qs = qs.filter(preparation_time__gte=min_value)
            if max_value is not None:
                qs = qs.filter(preparation_time__lte=max_value)
            order_field = (
                "-preparation_time" if order == "desc" else "preparation_time"
            )
            return list(qs.order_by(order_field))
        items = [
            item
            for item in MenuDataAccessLayer._get_public_active_items(branch_id)
            if item.preparation_time is not None
        ]
        if min_value is not None:
            items = [i for i in items if i.preparation_time >= min_value]
        if max_value is not None:
            items = [i for i in items if i.preparation_time <= max_value]
        return sorted(items, key=lambda i: i.preparation_time, reverse=(order == "desc"))

    @staticmethod
    def get_items_by_calories(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ) -> list[MenuItem]:
        if tags:
            qs = MenuDataAccessLayer._public_items_queryset(
                branch_id, tags=tags
            ).filter(calories__isnull=False)
            if min_value is not None:
                qs = qs.filter(calories__gte=min_value)
            if max_value is not None:
                qs = qs.filter(calories__lte=max_value)
            order_field = "-calories" if order == "desc" else "calories"
            return list(qs.order_by(order_field))
        items = [
            item
            for item in MenuDataAccessLayer._get_public_active_items(branch_id)
            if item.calories is not None
        ]
        if min_value is not None:
            items = [i for i in items if i.calories >= min_value]
        if max_value is not None:
            items = [i for i in items if i.calories <= max_value]
        return sorted(items, key=lambda i: i.calories, reverse=(order == "desc"))

    @staticmethod
    def get_items_by_discount(
        branch_id,
        has_discount=None,
        min_value=None,
        max_value=None,
        order=None,
        *,
        tags=None,
    ) -> list[MenuItem]:
        if tags:
            qs = MenuDataAccessLayer._public_items_queryset(branch_id, tags=tags)
            if has_discount is True:
                qs = qs.filter(discount__gt=0)
            elif has_discount is False:
                qs = qs.filter(discount=0)
            if min_value is not None:
                qs = qs.filter(discount__gte=min_value)
            if max_value is not None:
                qs = qs.filter(discount__lte=max_value)
            order_field = "-discount" if order == "desc" else "discount"
            return list(qs.order_by(order_field))
        items = MenuDataAccessLayer._get_public_active_items(branch_id)
        if has_discount is True:
            items = [i for i in items if i.discount > 0]
        elif has_discount is False:
            items = [i for i in items if i.discount == 0]
        if min_value is not None:
            items = [i for i in items if i.discount >= min_value]
        if max_value is not None:
            items = [i for i in items if i.discount <= max_value]
        return sorted(items, key=lambda i: i.discount, reverse=(order == "desc"))

    @staticmethod
    def get_items_count(branch_id) -> int:
        return queryset_public_active_items(branch_id).count()

    @staticmethod
    def get_categories_count(branch_id) -> int:
        return len(MenuDataAccessLayer.get_categories_with_items(branch_id))

    @staticmethod
    def filter_items(
        branch_id,
        *,
        category=None,
        search=None,
        min_price=None,
        max_price=None,
        min_rating=None,
        available=None,
        sort=None,
        tags=None,
    ) -> list[MenuItem]:
        if tags:
            return list(
                MenuDataAccessLayer._filter_items_queryset(
                    branch_id,
                    category=category,
                    search=search,
                    min_price=min_price,
                    max_price=max_price,
                    min_rating=min_rating,
                    available=available,
                    sort=sort,
                    tags=tags,
                )
            )

        items = MenuDataAccessLayer._get_public_active_items(branch_id)

        # Optional ordering filter — never used for default public visibility.
        if available is not None:
            items = [item for item in items if item.available is available]

        if category:
            category_value = str(category).lower()
            items = [
                item
                for item in items
                if str(item.category_id) == category
                or (item.category and item.category.slug.lower() == category_value)
            ]

        if search:
            query = search.lower()
            items = [
                item
                for item in items
                if query in item.name.lower()
                or query in (item.description or "").lower()
                or any(query in tag.slug.lower() for tag in item.tags.all())
            ]

        if min_price is not None:
            items = [item for item in items if item.price >= min_price]
        if max_price is not None:
            items = [item for item in items if item.price <= max_price]
        if min_rating is not None:
            items = [
                item
                for item in items
                if float(compute_rating()) >= float(min_rating)
            ]

        if sort == "price_asc":
            items.sort(key=lambda item: item.price)
        elif sort == "price_desc":
            items.sort(key=lambda item: item.price, reverse=True)
        elif sort == "rating":
            items.sort(
                key=lambda item: float(compute_rating()),
                reverse=True,
            )
        elif sort == "newest":
            items.sort(key=lambda item: item.created_at, reverse=True)
        elif sort == "popular":
            items.sort(
                key=lambda item: (
                    item.is_popular,
                    compute_rating_count(),
                    item.created_at,
                ),
                reverse=True,
            )

        return items

    @staticmethod
    def _filter_items_queryset(
        branch_id,
        *,
        category=None,
        search=None,
        min_price=None,
        max_price=None,
        min_rating=None,
        available=None,
        sort=None,
        tags=None,
    ):
        qs = queryset_public_active_items(branch_id).prefetch_related(
            *_ITEM_PREFETCH
        )

        if tags:
            qs = qs.filter(tags__id__in=tags).distinct()

        if available is not None:
            qs = qs.filter(available=available)

        if category:
            category_value = str(category).lower()
            qs = qs.filter(
                Q(category_id=category)
                | Q(category__slug__iexact=category_value)
            )

        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(tags__name__icontains=search)
                | Q(tags__slug__icontains=search)
            ).distinct()

        if min_price is not None:
            qs = qs.filter(price__gte=min_price)
        if max_price is not None:
            qs = qs.filter(price__lte=max_price)

        if sort == "price_asc":
            qs = qs.order_by("price")
        elif sort == "price_desc":
            qs = qs.order_by("-price")
        elif sort == "newest":
            qs = qs.order_by("-created_at")
        elif sort == "popular":
            qs = qs.order_by("-is_popular", "-created_at")
        else:
            qs = qs.order_by("name")

        items = list(qs)
        if min_rating is not None:
            items = [
                item
                for item in items
                if float(compute_rating()) >= float(min_rating)
            ]
        if sort == "rating":
            items.sort(
                key=lambda item: float(compute_rating()),
                reverse=True,
            )
        return items

    @staticmethod
    def search_items(branch_id, query: str, *, tags=None) -> list[MenuItem]:
        return MenuDataAccessLayer.filter_items(
            branch_id,
            search=query,
            tags=tags,
        )

    @staticmethod
    def get_related_items(
        branch_id, item_id, *, limit: int = 4, tags=None
    ) -> list[MenuItem]:
        if tags:
            source = (
                MenuDataAccessLayer._public_items_queryset(branch_id)
                .filter(id=item_id)
                .first()
            )
            if source is None:
                return []
            qs = MenuDataAccessLayer._public_items_queryset(
                branch_id,
                tags=tags,
                category_id=source.category_id,
                exclude_item_id=source.id,
            ).order_by("name")[:limit]
            return list(qs)

        items = MenuDataAccessLayer._get_public_active_items(branch_id)
        source = next((item for item in items if str(item.id) == str(item_id)), None)
        if source is None:
            return []

        related = [
            item
            for item in items
            if item.category_id == source.category_id
            and item.id != source.id
        ]
        return related[:limit]