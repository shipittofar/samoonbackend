from django.db import transaction
from django.db.models import Q

from core.cache import cache_get, cache_set, cache_delete
from core.cache import CacheKeys
from core.utils.slug import generate_random_slug
from menu.models import MenuCategory
from tenants.models import Branch
from core.utils.slug import assign_unique_slug
from core.cache import CacheTTL


CATEGORY_TTL = CacheTTL.MENU_CATEGORY


class CategoryDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_category_list_cache(branch_id) -> list[MenuCategory]:
        """
        Reads the fresh category list from the database and writes it to
        cache. Used both on cache miss and right after any write, so the
        next read always sees up-to-date data (write-through).
        """
        data = list(MenuCategory.objects.filter(branch_id=branch_id))
        key = CacheKeys.MENU_CATEGORY_LIST.format(branch_id=branch_id)
        cache_set(key, data, CATEGORY_TTL)
        return data

    @staticmethod
    def _refresh_category_detail_cache(category_id, branch_id) -> MenuCategory | None:
        instance = MenuCategory.objects.filter(
            id=category_id,
            branch_id=branch_id,
        ).first()
        key = CacheKeys.MENU_CATEGORY_DETAIL.format(
            branch_id=branch_id, category_id=category_id)
        if instance is not None:
            cache_set(key, instance, CATEGORY_TTL)
        else:
            cache_delete(key)
        return instance

    @staticmethod
    def invalidate_category_cache(branch_id, category_id=None) -> None:
        """
        Called after any create/update/delete/bulk_create that touches
        categories of this branch. Refreshes the list cache immediately,
        and refreshes (or clears) the detail cache if a specific
        category_id is affected.
        """
        from menu.selectors.menu_dal import MenuDataAccessLayer

        CategoryDataAccessLayer._refresh_category_list_cache(branch_id)
        if category_id is not None:
            CategoryDataAccessLayer._refresh_category_detail_cache(
                category_id, branch_id)

        # a category create/rename/delete also changes the browse-page
        # categories-with-items view, so keep that cache in sync too
        MenuDataAccessLayer.invalidate_categories_with_items_cache(branch_id)

    # ---------- reads (cached) ----------

    @staticmethod
    def get_all_categories(branch_id):
        key = CacheKeys.MENU_CATEGORY_LIST.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return CategoryDataAccessLayer._refresh_category_list_cache(branch_id)

    @staticmethod
    def get_menu_category_by_id(
            category_id,
            branch_id,
    ) -> MenuCategory | None:
        key = CacheKeys.MENU_CATEGORY_DETAIL.format(
            branch_id=branch_id, category_id=category_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return CategoryDataAccessLayer._refresh_category_detail_cache(category_id, branch_id)

    # ---------- reads (not cached — validation / admin / owner-scoped) ----------

    @staticmethod
    def branch_exists(branch_id) -> bool:
        return Branch.objects.filter(id=branch_id).exists()

    @staticmethod
    def category_exists(
            branch_id,
            name: str,
            exclude_id=None,
    ) -> bool:
        queryset = MenuCategory.objects.filter(
            branch_id=branch_id,
            name=name,
        )

        if exclude_id is not None:
            queryset = queryset.exclude(id=exclude_id)

        return queryset.exists()

    @staticmethod
    def get_missing_branch_ids(branch_ids: set) -> set:
        existing = set(
            Branch.objects.filter(
                id__in=branch_ids).values_list("id", flat=True)
        )
        return branch_ids - existing

    @staticmethod
    def get_existing_category_pairs(
            pairs: list
    ) -> set:
        q = Q()
        for branch_id, name in pairs:
            q |= Q(branch_id=branch_id, name=name)

        return set(
            MenuCategory.objects.filter(q).values_list("branch_id", "name")
        )

    @staticmethod
    def get_all_categories_unfiltered():
        # Admin-wide listing, not scoped to a single branch — left uncached
        # on purpose since it's low-traffic and caching it well would need
        # a different invalidation strategy (every category write everywhere).
        return MenuCategory.objects.all()

    @staticmethod
    def get_categories_by_owner(user):
        return MenuCategory.objects.filter(branch__tenant__owner__user=user)

    @staticmethod
    def get_category_by_id_for_owner(category_id, user) -> MenuCategory | None:
        return MenuCategory.objects.filter(
            id=category_id,
            branch__tenant__owner__user=user,
        ).first()

    @staticmethod
    def get_categories_by_owner_tenant_branch(user, tenant_id, branch_id):
        return MenuCategory.objects.filter(
            branch_id=branch_id,
            branch__tenant_id=tenant_id,
            branch__tenant__owner__user=user,
        )

    @staticmethod
    def get_categories_by_owner_branch(branch_id, user):
        return MenuCategory.objects.filter(
            branch_id=branch_id,
            branch__tenant__owner__user=user,
        )

    @staticmethod
    def branch_belongs_to_owner(branch_id, tenant_id, user) -> bool:
        return Branch.objects.filter(
            id=branch_id,
            tenant_id=tenant_id,
            tenant__owner__user=user,
        ).exists()

    # ---------- writes (trigger cache refresh via transaction.on_commit) ----------

    @staticmethod
    def create_category(
        branch_id,
        name: str,
        description: str = "",
        image=None,
        sort_order: int = 0,
    ) -> MenuCategory:
        # slug is auto-generated in MenuCategory.save(), no need to pass it here
        category = MenuCategory.objects.create(
            branch_id=branch_id,
            name=name,
            description=description,
            image=image,
            sort_order=sort_order,
        )
        transaction.on_commit(
            lambda: CategoryDataAccessLayer.invalidate_category_cache(
                branch_id, category.id)
        )
        return category

    @staticmethod
    def _generate_unique_slug(used_slugs: set) -> str:
        # bulk_create does NOT call save(), so slug must be generated manually here.
        # used_slugs tracks slugs already assigned in this batch, since none of
        # them exist in the DB yet to be caught by the .exists() check.
        slug = generate_random_slug()
        while slug in used_slugs or MenuCategory.objects.filter(slug=slug).exists():
            slug = generate_random_slug()
        return slug

    @staticmethod
    def bulk_create_categories(items: list[dict]) -> list[MenuCategory]:
        used_slugs: set = set()
        objs = []

        for item in items:
            obj = MenuCategory(
                branch_id=item["branch_id"],
                name=item["name"],
                description=item.get("description", ""),
                image=item.get("image"),
                sort_order=item.get("sort_order", 0),
            )

            assign_unique_slug(obj, MenuCategory)
            while obj.slug in used_slugs:
                obj.slug = ""
                assign_unique_slug(obj, MenuCategory)
            used_slugs.add(obj.slug)

            objs.append(obj)

        created = MenuCategory.objects.bulk_create(objs)

        affected_branch_ids = {item["branch_id"] for item in items}
        transaction.on_commit(
            lambda: [
                CategoryDataAccessLayer.invalidate_category_cache(branch_id)
                for branch_id in affected_branch_ids
            ]
        )
        return created

    @staticmethod
    def update_category(
        category: MenuCategory,
        name: str | None = None,
        description: str | None = None,
        image=None,
        image_provided: bool = False,
        sort_order: int | None = None,
    ) -> MenuCategory:
        if name is not None:
            category.name = name
        if description is not None:
            category.description = description
        if image_provided:
            if category.image:
                category.image.delete(save=False)
            category.image = image
        if sort_order is not None:
            category.sort_order = sort_order
        category.save()

        transaction.on_commit(
            lambda: CategoryDataAccessLayer.invalidate_category_cache(
                category.branch_id, category.id)
        )
        return category

    @staticmethod
    def delete_category(category: MenuCategory) -> None:
        from core.exceptions.category import CategoryHasItemsException
        from menu.models import MenuItem

        if MenuItem.all_objects.filter(category_id=category.id).exists():
            raise CategoryHasItemsException()

        branch_id = category.branch_id
        category_id = category.id
        category.delete()

        def _on_commit():
            CategoryDataAccessLayer._refresh_category_list_cache(branch_id)
            cache_delete(
                CacheKeys.MENU_CATEGORY_DETAIL.format(
                    branch_id=branch_id, category_id=category_id)
            )

        transaction.on_commit(_on_commit)
