from django.db import transaction
from django.db.models import Q

from core.cache import cache_get, cache_set, cache_delete
from core.cache import CacheKeys
from core.utils.slug import assign_unique_slug
from menu.models import MenuItem, MenuCategory, Extra, MenuItemExtra
from core.cache import CacheTTL


MENU_ITEM_TTL = CacheTTL.MENU_ITEM
EXTRA_TTL = CacheTTL.EXTRA
MENU_ITEM_EXTRA_TTL = CacheTTL.MENU_ITEM_EXTRA


class ItemDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_item_list_cache(branch_id, category_id) -> list[MenuItem]:
        """
        Rebuilds the cached item list for a branch/category from the
        database. Used on cache miss and right after any write, so reads
        right after a write never see stale data.
        """
        data = list(
            MenuItem.objects.filter(
                branch_id=branch_id,
                category_id=category_id,
            ).prefetch_related("tags")
        )
        key = CacheKeys.MENU_ITEM_LIST.format(
            branch_id=branch_id, category_id=category_id)
        cache_set(key, data, MENU_ITEM_TTL)
        return data

    @staticmethod
    def _refresh_item_list_for_console_cache(branch_id) -> list[MenuItem]:
        data = list(
            MenuItem.objects.filter(
                branch_id=branch_id,
            ).prefetch_related("tags")
        )
        key = CacheKeys.MENU_ITEM_LIST_FOR_CONSOLE.format(branch_id=branch_id)
        cache_set(key, data, MENU_ITEM_TTL)
        return data

    @staticmethod
    def _refresh_item_detail_cache(item_id, category_id, branch_id) -> MenuItem | None:
        instance = MenuItem.objects.filter(
            id=item_id,
            category_id=category_id,
            branch_id=branch_id,
        ).prefetch_related("tags").first()
        key = CacheKeys.MENU_ITEM_DETAIL.format(
            branch_id=branch_id, category_id=category_id, item_id=item_id
        )
        if instance is not None:
            cache_set(key, instance, MENU_ITEM_TTL)
        else:
            cache_delete(key)
        return instance

    @staticmethod
    def invalidate_item_cache(branch_id, category_id, item_id=None) -> None:
        """
        Called after any create/update/delete/bulk_create that touches
        categories of this branch. Refreshes the list cache immediately,
        and refreshes (or clears) the detail cache if a specific
        category_id is affected.
        """
        from menu.selectors.menu_dal import MenuDataAccessLayer

        ItemDataAccessLayer._refresh_item_list_cache(branch_id, category_id)
        if item_id is not None:
            ItemDataAccessLayer._refresh_item_detail_cache(
                item_id, category_id, branch_id)

        MenuDataAccessLayer.invalidate_branch_items_cache(branch_id)
        MenuDataAccessLayer.invalidate_categories_with_items_cache(branch_id)

    # ---------- reads (cached) ----------

    @staticmethod
    def get_all_items(branch_id, category_id):
        key = CacheKeys.MENU_ITEM_LIST.format(
            branch_id=branch_id, category_id=category_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return ItemDataAccessLayer._refresh_item_list_cache(branch_id, category_id)

    @staticmethod
    def get_all_items_for_console(branch_id):
        return list(MenuItem.objects.filter(
            branch_id=branch_id
        ).prefetch_related(
            "tags",
            "item_extras__extra",
            "item_extra_groups",
            "category",
        ))

        # key = CacheKeys.MENU_ITEM_LIST_FOR_CONSOLE.format(branch_id=branch_id)
        # cached = cache_get(key)
        # if cached is not None:
        #     return cached
        # return ItemDataAccessLayer._refresh_item_list_for_console_cache(branch_id)

    @staticmethod
    def get_item_by_id_and_context(
        item_id,
        category_id,
        branch_id,
    ) -> MenuItem | None:
        key = CacheKeys.MENU_ITEM_DETAIL.format(
            branch_id=branch_id, category_id=category_id, item_id=item_id
        )
        cached = cache_get(key)
        if cached is not None:
            return cached
        return ItemDataAccessLayer._refresh_item_detail_cache(item_id, category_id, branch_id)

    # ---------- reads (not cached — validation only) ----------

    @staticmethod
    def get_item_by_id(item_id) -> MenuItem | None:
        return MenuItem.objects.filter(id=item_id).first()

    @staticmethod
    def category_exists(category_id, branch_id) -> bool:
        return MenuCategory.objects.filter(
            id=category_id,
            branch_id=branch_id,
        ).exists()

    @staticmethod
    def get_missing_tag_ids(tag_ids: set, branch_id) -> set:
        from menu.selectors.tag_dal import TagDataAccessLayer

        return TagDataAccessLayer.get_missing_tag_ids(tag_ids, branch_id)

    @staticmethod
    def get_existing_category_ids(category_ids: set, branch_id) -> set:
        return set(
            MenuCategory.objects.filter(
                id__in=category_ids,
                branch_id=branch_id,
            ).values_list("id", flat=True)
        )

    @staticmethod
    def get_existing_item_pairs(pairs: list) -> set:
        q = Q()
        for category_id, name in pairs:
            q |= Q(category_id=category_id, name=name)

        return set(
            MenuItem.objects.filter(q).values_list("category_id", "name")
        )

    @staticmethod
    def item_exists(category_id, name: str, exclude_id=None) -> bool:
        qs = MenuItem.objects.filter(category_id=category_id, name=name)
        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    # ---------- writes (trigger cache refresh via transaction.on_commit) ----------

    @staticmethod
    def create_item(
        branch_id,
        category_id,
        name: str,
        price: float,
        description: str = "",
        discount: float = 0,
        image=None,
        calories: int | None = None,
        preparation_time: int | None = None,
        is_active: bool = True,
        available: bool = True,
        is_popular: bool = False,
        is_featured: bool = False,
        tag_ids: list | None = None,
    ) -> MenuItem:
        item = MenuItem.objects.create(
            branch_id=branch_id,
            category_id=category_id,
            name=name,
            price=price,
            description=description,
            discount=discount,
            image=image,
            calories=calories,
            preparation_time=preparation_time,
            is_active=is_active,
            available=available,
            is_popular=is_popular,
            is_featured=is_featured,
        )
        if tag_ids:
            item.tags.set(tag_ids)

        transaction.on_commit(
            lambda: ItemDataAccessLayer.invalidate_item_cache(
                branch_id, category_id, item.id)
        )
        return item

    @staticmethod
    def bulk_create_items(items: list[dict]) -> list[MenuItem]:
        # bulk_create doesn't call save(), so the slug must be generated
        # manually here (same pattern as MenuCategory.bulk_create_categories).
        used_slugs: set = set()
        objs = []

        for item in items:
            obj = MenuItem(
                branch_id=item["branch_id"],
                category_id=item["category_id"],
                name=item["name"],
                description=item.get("description", ""),
                price=item["price"],
                discount=item.get("discount", 0),
                image=item.get("image"),
                calories=item.get("calories"),
                preparation_time=item.get("preparation_time"),
                is_active=item.get("is_active", True),
                available=item.get("available", True),
                is_popular=item.get("is_popular", False),
                is_featured=item.get("is_featured", False),
            )

            assign_unique_slug(obj, MenuItem)
            while obj.slug in used_slugs:
                obj.slug = ""
                assign_unique_slug(obj, MenuItem)
            used_slugs.add(obj.slug)

            objs.append(obj)

        created = MenuItem.objects.bulk_create(objs)

        # bulk_create returns objects with pks populated (postgres/sqlite),
        # so the M2M through table can be filled in directly.
        through_model = MenuItem.tags.through
        through_objs = [
            through_model(menuitem_id=created_obj.id, tag_id=tag_id)
            for item_data, created_obj in zip(items, created)
            for tag_id in (item_data.get("tag_ids") or [])
        ]
        if through_objs:
            through_model.objects.bulk_create(
                through_objs, ignore_conflicts=True)

        affected = {(item["branch_id"], item["category_id"]) for item in items}
        transaction.on_commit(
            lambda: [
                ItemDataAccessLayer.invalidate_item_cache(
                    branch_id, category_id)
                for branch_id, category_id in affected
            ]
        )
        return created

    @staticmethod
    def update_item(
        item: MenuItem,
        name: str | None = None,
        description: str | None = None,
        price: float | None = None,
        discount: float | None = None,
        image=None,
        image_provided: bool = False,
        calories: int | None = None,
        preparation_time: int | None = None,
        is_active: bool | None = None,
        available: bool | None = None,
        is_popular: bool | None = None,
        is_featured: bool | None = None,
        tag_ids: list | None = None,
        tag_ids_provided: bool = False,
    ) -> MenuItem:
        fields = ["updated_at"]

        if name is not None:
            item.name = name
            fields.append("name")
        if description is not None:
            item.description = description
            fields.append("description")
        if price is not None:
            item.price = price
            fields.append("price")
        if discount is not None:
            item.discount = discount
            fields.append("discount")
        if image_provided:
            if item.image:
                item.image.delete(save=False)
            item.image = image
            fields.append("image")
        if calories is not None:
            item.calories = calories
            fields.append("calories")
        if preparation_time is not None:
            item.preparation_time = preparation_time
            fields.append("preparation_time")
        if is_active is not None:
            item.is_active = is_active
            fields.append("is_active")
        if available is not None:
            item.available = available
            fields.append("available")
        if is_popular is not None:
            item.is_popular = is_popular
            fields.append("is_popular")
        if is_featured is not None:
            item.is_featured = is_featured
            fields.append("is_featured")

        item.save(update_fields=fields)

        if tag_ids_provided:
            item.tags.set(tag_ids or [])

        transaction.on_commit(
            lambda: ItemDataAccessLayer.invalidate_item_cache(
                item.branch_id, item.category_id, item.id
            )
        )
        return item

    @staticmethod
    def delete_item(item: MenuItem) -> None:
        branch_id, category_id, item_id = item.branch_id, item.category_id, item.id
        item.delete()

        def _on_commit():
            ItemDataAccessLayer._refresh_item_list_cache(
                branch_id, category_id)
            cache_delete(
                CacheKeys.MENU_ITEM_DETAIL.format(
                    branch_id=branch_id, category_id=category_id, item_id=item_id
                )
            )

        transaction.on_commit(_on_commit)


class ExtraDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_extra_list_cache(branch_id) -> list[Extra]:
        data = list(Extra.objects.filter(branch_id=branch_id))
        key = CacheKeys.EXTRA_LIST.format(branch_id=branch_id)
        cache_set(key, data, EXTRA_TTL)
        return data

    @staticmethod
    def _refresh_extra_detail_cache(extra_id, branch_id) -> Extra | None:
        instance = Extra.objects.filter(
            id=extra_id, branch_id=branch_id).first()
        key = CacheKeys.EXTRA_DETAIL.format(
            branch_id=branch_id, extra_id=extra_id)
        if instance is not None:
            cache_set(key, instance, EXTRA_TTL)
        else:
            cache_delete(key)
        return instance

    @staticmethod
    def invalidate_extra_cache(branch_id, extra_id=None) -> None:
        ExtraDataAccessLayer._refresh_extra_list_cache(branch_id)
        if extra_id is not None:
            ExtraDataAccessLayer._refresh_extra_detail_cache(
                extra_id, branch_id)

    # ---------- reads (cached) ----------

    @staticmethod
    def get_all_extras(branch_id, group_id=None):
        key = CacheKeys.EXTRA_LIST.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            extras = cached
        else:
            extras = ExtraDataAccessLayer._refresh_extra_list_cache(branch_id)
        if group_id is not None:
            return [e for e in extras if e.group_id == group_id]
        return extras

    @staticmethod
    def get_extra_by_id(extra_id, branch_id) -> Extra | None:
        key = CacheKeys.EXTRA_DETAIL.format(
            branch_id=branch_id, extra_id=extra_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return ExtraDataAccessLayer._refresh_extra_detail_cache(extra_id, branch_id)

    # ---------- reads (not cached) ----------

    @staticmethod
    def extra_exists(branch_id, name: str, exclude_id=None) -> bool:
        qs = Extra.objects.filter(branch_id=branch_id, name=name)
        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    @staticmethod
    def get_extra_group_by_id_and_branch(group_id, branch_id):
        from menu.models import ExtraGroup
        return ExtraGroup.objects.filter(id=group_id, branch_id=branch_id).first()

    # ---------- writes ----------

    @staticmethod
    def create_extra(
        branch_id,
        name: str,
        price: float,
        available: bool = True,
        group_id=None,
        description: str = "",
        order: int = 0,
    ) -> Extra:
        extra = Extra.objects.create(
            branch_id=branch_id,
            group_id=group_id,
            name=name,
            description=description,
            price=price,
            available=available,
            order=order,
        )
        transaction.on_commit(
            lambda: ExtraDataAccessLayer.invalidate_extra_cache(
                branch_id, extra.id)
        )
        return extra

    @staticmethod
    def update_extra(
        extra: Extra,
        name: str | None = None,
        price: float | None = None,
        available: bool | None = None,
        group_id=None,
        group_id_provided: bool = False,
        description: str | None = None,
        order: int | None = None,
    ) -> Extra:
        price_changed = price is not None and price != extra.price
        availability_changed = available is not None and available != extra.available
        group_changed = group_id_provided and group_id != extra.group_id

        if name is not None:
            extra.name = name
        if price is not None:
            extra.price = price
        if available is not None:
            extra.available = available
        if group_id_provided:
            extra.group_id = group_id
        if description is not None:
            extra.description = description
        if order is not None:
            extra.order = order
        extra.save()

        def _on_commit():
            ExtraDataAccessLayer.invalidate_extra_cache(
                extra.branch_id, extra.id)
            if price_changed:
                MenuItemExtraDataAccessLayer.invalidate_links_by_extra(
                    extra.id)
            if availability_changed or group_changed:
                from menu.selectors.extra_group_dal import (
                    MenuItemExtraGroupDataAccessLayer,
                )
                if extra.group_id:
                    MenuItemExtraGroupDataAccessLayer.sync_items_for_group(
                        extra.group_id, extra.branch_id
                    )

        transaction.on_commit(_on_commit)
        return extra

    @staticmethod
    def delete_extra(extra: Extra) -> None:
        branch_id, extra_id = extra.branch_id, extra.id
        extra.delete()

        def _on_commit():
            ExtraDataAccessLayer._refresh_extra_list_cache(branch_id)
            cache_delete(CacheKeys.EXTRA_DETAIL.format(
                branch_id=branch_id, extra_id=extra_id))

        transaction.on_commit(_on_commit)


class MenuItemExtraDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_link_list_cache(item_id) -> list[MenuItemExtra]:
        data = list(
            MenuItemExtra.objects.filter(
                item_id=item_id).select_related("extra")
        )
        key = CacheKeys.MENU_ITEM_EXTRA_LIST.format(item_id=item_id)
        cache_set(key, data, MENU_ITEM_EXTRA_TTL)
        return data

    @staticmethod
    def invalidate_links_by_extra(extra_id) -> None:
        """
        Refreshes the extras-list cache for every item linked to this
        extra. Needed because a Extra price change silently changes the
        effective price of any MenuItemExtra without its own override.
        """
        item_ids = MenuItemExtra.objects.filter(extra_id=extra_id).values_list(
            "item_id", flat=True
        ).distinct()
        for item_id in item_ids:
            MenuItemExtraDataAccessLayer._refresh_link_list_cache(item_id)

    # ---------- reads (cached) ----------

    @staticmethod
    def get_all_links(item_id):
        key = CacheKeys.MENU_ITEM_EXTRA_LIST.format(item_id=item_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return MenuItemExtraDataAccessLayer._refresh_link_list_cache(item_id)

    # ---------- reads (not cached) ----------

    @staticmethod
    def get_item_by_id_and_branch(item_id, branch_id) -> MenuItem | None:
        return MenuItem.objects.filter(id=item_id, branch_id=branch_id).first()

    @staticmethod
    def get_extra_by_id_and_branch(extra_id, branch_id) -> Extra | None:
        return Extra.objects.filter(id=extra_id, branch_id=branch_id).first()

    @staticmethod
    def link_exists(item_id, extra_id) -> bool:
        return MenuItemExtra.objects.filter(
            item_id=item_id, extra_id=extra_id
        ).exists()

    @staticmethod
    def get_link(item_id, extra_id) -> MenuItemExtra | None:
        return MenuItemExtra.objects.filter(
            item_id=item_id, extra_id=extra_id
        ).select_related("extra").first()

    # ---------- writes ----------

    @staticmethod
    def create_link(
        item_id,
        extra_id,
        price_override: float | None = None,
    ) -> MenuItemExtra:
        link = MenuItemExtra.objects.create(
            item_id=item_id,
            extra_id=extra_id,
            price_override=price_override,
        )
        transaction.on_commit(
            lambda: MenuItemExtraDataAccessLayer._refresh_link_list_cache(
                item_id)
        )
        return link

    @staticmethod
    def update_link(
        link: MenuItemExtra,
        price_override=None,
        price_override_provided: bool = False,
    ) -> MenuItemExtra:
        if price_override_provided:
            link.price_override = price_override
            link.save(update_fields=["price_override"])
            transaction.on_commit(
                lambda: MenuItemExtraDataAccessLayer._refresh_link_list_cache(
                    link.item_id)
            )
        return link

    @staticmethod
    def delete_link(link: MenuItemExtra) -> None:
        item_id = link.item_id
        link.delete()
        transaction.on_commit(
            lambda: MenuItemExtraDataAccessLayer._refresh_link_list_cache(
                item_id)
        )
