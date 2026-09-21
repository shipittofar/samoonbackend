from django.db import transaction

from core.cache import cache_get, cache_set, cache_delete
from core.cache import CacheKeys, CacheTTL
from menu.models import ExtraGroup, MenuItemExtraGroup, Extra, MenuItemExtra


EXTRA_GROUP_TTL = CacheTTL.EXTRA_GROUP


class ExtraGroupDataAccessLayer:

    # ---------- cache helpers ----------

    @staticmethod
    def _refresh_extra_group_list_cache(branch_id) -> list[ExtraGroup]:
        data = list(ExtraGroup.objects.filter(
            branch_id=branch_id).order_by("order"))
        key = CacheKeys.EXTRA_GROUP_LIST.format(branch_id=branch_id)
        cache_set(key, data, EXTRA_GROUP_TTL)
        return data

    @staticmethod
    def _refresh_extra_group_detail_cache(group_id, branch_id) -> ExtraGroup | None:
        instance = ExtraGroup.objects.filter(
            id=group_id, branch_id=branch_id
        ).first()
        key = CacheKeys.EXTRA_GROUP_DETAIL.format(
            branch_id=branch_id, group_id=group_id
        )
        if instance is not None:
            cache_set(key, instance, EXTRA_GROUP_TTL)
        else:
            cache_delete(key)
        return instance

    @staticmethod
    def invalidate_extra_group_cache(branch_id, group_id=None) -> None:
        ExtraGroupDataAccessLayer._refresh_extra_group_list_cache(branch_id)
        if group_id is not None:
            ExtraGroupDataAccessLayer._refresh_extra_group_detail_cache(
                group_id, branch_id
            )

    # ---------- reads (cached) ----------

    @staticmethod
    def get_all_extra_groups(branch_id):
        key = CacheKeys.EXTRA_GROUP_LIST.format(branch_id=branch_id)
        cached = cache_get(key)
        if cached is not None:
            return cached
        return ExtraGroupDataAccessLayer._refresh_extra_group_list_cache(branch_id)

    @staticmethod
    def get_all_extra_groups_for_console(branch_id) -> list[ExtraGroup]:
        print(branch_id)
        print(type(branch_id))
        groups = ExtraGroup.objects.filter(
            branch_id=branch_id
        ).order_by("order")
        return groups

    @staticmethod
    def get_extra_group_by_id(group_id, branch_id) -> ExtraGroup | None:
        key = CacheKeys.EXTRA_GROUP_DETAIL.format(
            branch_id=branch_id, group_id=group_id
        )
        cached = cache_get(key)
        if cached is not None:
            return cached
        return ExtraGroupDataAccessLayer._refresh_extra_group_detail_cache(
            group_id, branch_id
        )

    # ---------- reads (not cached) ----------

    @staticmethod
    def extra_group_exists(branch_id, name: str, exclude_id=None) -> bool:
        qs = ExtraGroup.objects.filter(branch_id=branch_id, name=name)
        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    @staticmethod
    def get_groups_by_ids(group_ids, branch_id) -> list[ExtraGroup]:
        if not group_ids:
            return []
        return list(
            ExtraGroup.objects.filter(id__in=group_ids, branch_id=branch_id)
        )

    @staticmethod
    def get_item_extra_group_ids(item_id) -> list:
        return list(
            MenuItemExtraGroup.objects.filter(item_id=item_id).values_list(
                "extra_group_id", flat=True
            )
        )

    # ---------- writes ----------

    @staticmethod
    def create_extra_group(
        branch_id,
        name: str,
        selection_type: str,
        required: bool = False,
        min_selection: int = 0,
        max_selection: int = 1,
        order: int = 0,
        is_active: bool = True,
        description: str = "",
    ) -> ExtraGroup:
        group = ExtraGroup.objects.create(
            branch_id=branch_id,
            name=name,
            description=description,
            selection_type=selection_type,
            required=required,
            min_selection=min_selection,
            max_selection=max_selection,
            order=order,
            is_active=is_active,
        )
        transaction.on_commit(
            lambda: ExtraGroupDataAccessLayer.invalidate_extra_group_cache(
                branch_id, group.id
            )
        )
        return group

    @staticmethod
    def update_extra_group(
        group: ExtraGroup,
        name: str | None = None,
        description: str | None = None,
        selection_type: str | None = None,
        required: bool | None = None,
        min_selection: int | None = None,
        max_selection: int | None = None,
        order: int | None = None,
        is_active: bool | None = None,
    ) -> ExtraGroup:
        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if selection_type is not None:
            group.selection_type = selection_type
        if required is not None:
            group.required = required
        if min_selection is not None:
            group.min_selection = min_selection
        if max_selection is not None:
            group.max_selection = max_selection
        if order is not None:
            group.order = order
        if is_active is not None:
            group.is_active = is_active
        group.save()

        transaction.on_commit(
            lambda: ExtraGroupDataAccessLayer.invalidate_extra_group_cache(
                group.branch_id, group.id
            )
        )
        return group

    @staticmethod
    def delete_extra_group(group: ExtraGroup) -> None:
        branch_id, group_id = group.branch_id, group.id
        if group.extras.exists():
            group.is_active = False
            group.save(update_fields=["is_active"])
            transaction.on_commit(
                lambda: ExtraGroupDataAccessLayer._refresh_extra_group_list_cache(branch_id)
            )
            return

        group.delete()

        def _on_commit():
            ExtraGroupDataAccessLayer._refresh_extra_group_list_cache(
                branch_id)
            cache_delete(
                CacheKeys.EXTRA_GROUP_DETAIL.format(
                    branch_id=branch_id, group_id=group_id
                )
            )

        transaction.on_commit(_on_commit)

    @staticmethod
    def reorder_extra_groups(branch_id, ordered_ids: list) -> list[ExtraGroup]:
        groups = {
            g.id: g
            for g in ExtraGroup.objects.filter(
                branch_id=branch_id, id__in=ordered_ids
            )
        }
        to_update = []
        for index, group_id in enumerate(ordered_ids):
            group = groups.get(group_id)
            if group is not None:
                group.order = index
                to_update.append(group)
        if to_update:
            ExtraGroup.objects.bulk_update(to_update, ["order"])

        transaction.on_commit(
            lambda: ExtraGroupDataAccessLayer.invalidate_extra_group_cache(
                branch_id
            )
        )
        return list(
            ExtraGroup.objects.filter(branch_id=branch_id).order_by("order")
        )

    @staticmethod
    def replace_item_extra_groups(item_id, group_ids: list) -> None:
        MenuItemExtraGroup.objects.filter(item_id=item_id).delete()
        if group_ids:
            MenuItemExtraGroup.objects.bulk_create(
                [
                    MenuItemExtraGroup(item_id=item_id, extra_group_id=gid)
                    for gid in group_ids
                ]
            )


class MenuItemExtraGroupDataAccessLayer:

    @staticmethod
    def sync_item_extras_from_groups(item_id, branch_id) -> None:
        """
        Rebuild MenuItemExtra links from the item's assigned ExtraGroups.
        Only available extras in active groups are materialized.
        """
        from menu.selectors.item_dal import MenuItemExtraDataAccessLayer

        group_ids = list(
            MenuItemExtraGroup.objects.filter(item_id=item_id).values_list(
                "extra_group_id", flat=True
            )
        )

        if not group_ids:
            MenuItemExtra.objects.filter(item_id=item_id).delete()
            transaction.on_commit(
                lambda: MenuItemExtraDataAccessLayer._refresh_link_list_cache(
                    item_id
                )
            )
            return

        extra_ids = set(
            Extra.objects.filter(
                group_id__in=group_ids,
                branch_id=branch_id,
                available=True,
                group__is_active=True,
            ).values_list("id", flat=True)
        )

        existing_extra_ids = set(
            MenuItemExtra.objects.filter(item_id=item_id).values_list(
                "extra_id", flat=True
            )
        )

        to_remove = existing_extra_ids - extra_ids
        to_add = extra_ids - existing_extra_ids

        if to_remove:
            MenuItemExtra.objects.filter(
                item_id=item_id, extra_id__in=to_remove
            ).delete()

        if to_add:
            MenuItemExtra.objects.bulk_create(
                [
                    MenuItemExtra(item_id=item_id, extra_id=extra_id)
                    for extra_id in to_add
                ]
            )

        transaction.on_commit(
            lambda: MenuItemExtraDataAccessLayer._refresh_link_list_cache(
                item_id
            )
        )

    @staticmethod
    def sync_items_for_group(group_id, branch_id) -> None:
        """Re-sync MenuItemExtra for every item linked to this group."""
        item_ids = MenuItemExtraGroup.objects.filter(
            extra_group_id=group_id
        ).values_list("item_id", flat=True)
        for item_id in item_ids:
            MenuItemExtraGroupDataAccessLayer.sync_item_extras_from_groups(
                item_id, branch_id
            )
