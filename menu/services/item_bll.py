# menu/services/item_bll.py
from django.db import transaction

from menu.authorization.branch_menu import assert_branch_menu_write
from menu.models import Extra, MenuItemExtra, MenuItem
from menu.selectors import (
    ItemDataAccessLayer,
    CategoryDataAccessLayer,
    ExtraDataAccessLayer,
    MenuItemExtraDataAccessLayer,
    ExtraGroupDataAccessLayer,
)
from menu.selectors.extra_group_dal import MenuItemExtraGroupDataAccessLayer
from uploads.services.compat import apply_image_input
from core.exceptions import (
    CategoryNotFoundException,
    MenuItemAlreadyExistsException,
    BranchNotFoundException,
    MenuItemNotFoundException,
    TagNotFoundException,
    ExtraNotFoundException,
    ExtraAlreadyExistsException,
    MenuItemExtraAlreadyExistsException,
    MenuItemExtraNotFoundException,
    ExtraGroupNotFoundException,
    ExtraGroupNotActiveException,
)

item_dal = ItemDataAccessLayer()
category_dal = CategoryDataAccessLayer()
extra_dal = ExtraDataAccessLayer()
item_extra_dal = MenuItemExtraDataAccessLayer()
extra_group_dal = ExtraGroupDataAccessLayer()


class ItemBusinessLogicLayer:

    @staticmethod
    def create_menu_item(
        branch_id,
        category_id,
        name: str,
        price: float,
        description: str = "",
        discount: float = 0,
        image=None,
        image_asset_id=None,
        calories: int | None = None,
        preparation_time: int | None = None,
        is_active: bool = True,
        available: bool = True,
        is_popular: bool = False,
        is_featured: bool = False,
        tag_ids: list | None = None,
        user=None,
    ) -> MenuItem:

        if user is not None:
            assert_branch_menu_write(user, branch_id)
        elif not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        if not item_dal.category_exists(category_id, branch_id):
            raise CategoryNotFoundException()

        if item_dal.item_exists(category_id, name):
            raise MenuItemAlreadyExistsException()

        if tag_ids:
            missing_tags = item_dal.get_missing_tag_ids(set(tag_ids), branch_id)
            if missing_tags:
                raise TagNotFoundException()

        item = item_dal.create_item(
            branch_id=branch_id,
            category_id=category_id,
            name=name,
            price=price,
            description=description,
            discount=discount,
            image=None,
            calories=calories,
            preparation_time=preparation_time,
            is_active=is_active,
            available=available,
            is_popular=is_popular,
            is_featured=is_featured,
            tag_ids=tag_ids,
        )
        if user is not None and (image is not None or image_asset_id is not None):
            from tenants.models import Branch

            branch = Branch.objects.filter(id=branch_id).first()
            fields = apply_image_input(
                instance=item,
                user=user,
                image_field="image",
                asset_fk="image_asset",
                purpose="menu_item",
                tenant_id=getattr(branch, "tenant_id", None),
                file=image,
                file_provided=image is not None,
                asset_id=image_asset_id,
                asset_id_provided=image_asset_id is not None,
                entity_type="menu_item",
                entity_id=str(item.id),
                branch_id=branch_id,
                ingest_legacy=True,
            )
            if fields:
                item.save(update_fields=list(dict.fromkeys(fields)))
        elif image is not None:
            item.image = image
            item.save(update_fields=["image"])
        return item

    @staticmethod
    @transaction.atomic
    def bulk_create_menu_items(items: list[dict]) -> list[MenuItem]:
        seen = set()
        for item in items:
            key = (item["category_id"], item["name"])
            if key in seen:
                raise MenuItemAlreadyExistsException()
            seen.add(key)

        branch_ids = {item["branch_id"] for item in items}
        missing_branches = category_dal.get_missing_branch_ids(branch_ids)
        if missing_branches:
            raise BranchNotFoundException()

        branch_to_categories: dict = {}
        for item in items:
            branch_to_categories.setdefault(item["branch_id"], set()).add(
                item["category_id"]
            )

        for branch_id, category_ids in branch_to_categories.items():
            existing_categories = item_dal.get_existing_category_ids(
                category_ids, branch_id
            )
            if existing_categories != category_ids:
                raise CategoryNotFoundException()

        existing_pairs = item_dal.get_existing_item_pairs(
            [(item["category_id"], item["name"]) for item in items]
        )
        if existing_pairs:
            raise MenuItemAlreadyExistsException()

        all_tag_ids = {
            tag_id
            for item in items
            for tag_id in (item.get("tag_ids") or [])
        }
        if all_tag_ids:
            branch_to_tag_ids: dict = {}
            for item in items:
                branch_to_tag_ids.setdefault(item["branch_id"], set()).update(
                    item.get("tag_ids") or []
                )
            for branch_id, tag_ids in branch_to_tag_ids.items():
                missing_tags = item_dal.get_missing_tag_ids(tag_ids, branch_id)
                if missing_tags:
                    raise TagNotFoundException()

        return item_dal.bulk_create_items(items)

    @staticmethod
    def update_menu_item(
        item_id,
        category_id,
        branch_id,
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
        extra_group_ids: list | None = None,
        extra_group_ids_provided: bool = False,
        image_asset_id=None,
        image_asset_id_provided: bool = False,
        user=None,
    ) -> MenuItem:

        if user is not None:
            assert_branch_menu_write(user, branch_id)

        item = item_dal.get_item_by_id_and_context(
            item_id=item_id,
            category_id=category_id,
            branch_id=branch_id,
        )
        if item is None:
            raise MenuItemNotFoundException()

        if name is not None and item_dal.item_exists(
            category_id=item.category_id,
            name=name,
            exclude_id=item_id,
        ):
            raise MenuItemAlreadyExistsException()

        if tag_ids_provided and tag_ids:
            missing_tags = item_dal.get_missing_tag_ids(set(tag_ids), branch_id)
            if missing_tags:
                raise TagNotFoundException()

        if user is not None and (image_provided or image_asset_id_provided):
            from tenants.models import Branch

            branch = Branch.objects.filter(id=branch_id).first()
            apply_image_input(
                instance=item,
                user=user,
                image_field="image",
                asset_fk="image_asset",
                purpose="menu_item",
                tenant_id=getattr(branch, "tenant_id", None),
                file=image,
                file_provided=image_provided,
                asset_id=image_asset_id,
                asset_id_provided=image_asset_id_provided,
                entity_type="menu_item",
                entity_id=str(item.id),
                branch_id=branch_id,
                ingest_legacy=True,
            )
            image_provided = False
            image = None

        updated_item = item_dal.update_item(
            item=item,
            name=name,
            description=description,
            price=price,
            discount=discount,
            image=image,
            image_provided=image_provided,
            calories=calories,
            preparation_time=preparation_time,
            is_active=is_active,
            available=available,
            is_popular=is_popular,
            is_featured=is_featured,
            tag_ids=tag_ids,
            tag_ids_provided=tag_ids_provided,
        )

        if extra_group_ids_provided:
            MenuItemExtraGroupBusinessLogicLayer.assign_extra_groups_to_item(
                item_id=item_id,
                branch_id=branch_id,
                group_ids=extra_group_ids or [],
            )

        return updated_item

    @staticmethod
    def get_item_list(branch_id, category_id, *, tags=None):
        if tags:
            from menu.selectors.menu_dal import MenuDataAccessLayer

            return list(
                MenuDataAccessLayer._public_items_queryset(
                    branch_id,
                    tags=tags,
                    category_id=category_id,
                ).order_by("name")
            )
        return item_dal.get_all_items(
            branch_id=branch_id,
            category_id=category_id,
        )

    @staticmethod
    def get_item_list_for_console(branch_id):
        return item_dal.get_all_items_for_console(
            branch_id=branch_id,
        )

    @staticmethod
    def get_item_detail(
        item_id,
        category_id,
        branch_id,
    ) -> MenuItem:
        item = item_dal.get_item_by_id_and_context(
            item_id=item_id,
            category_id=category_id,
            branch_id=branch_id,
        )
        if item is None:
            raise MenuItemNotFoundException()
        return item

    @staticmethod
    def delete_menu_item(
        item_id,
        category_id,
        branch_id,
    ) -> None:
        item = item_dal.get_item_by_id_and_context(
            item_id=item_id,
            category_id=category_id,
            branch_id=branch_id,
        )
        if item is None:
            from menu.models import MenuItem

            item = MenuItem.all_objects.filter(
                id=item_id,
                category_id=category_id,
                branch_id=branch_id,
            ).first()
        if item is None:
            raise MenuItemNotFoundException()

        item_dal.delete_item(item)

    @staticmethod
    def restore_menu_item(item_id, category_id, branch_id) -> MenuItem:
        from menu.models import MenuItem

        item = MenuItem.all_objects.filter(
            id=item_id,
            category_id=category_id,
            branch_id=branch_id,
        ).first()
        if item is None:
            raise MenuItemNotFoundException()
        if item.deleted_at is not None:
            item.deleted_at = None
            item.save(update_fields=["deleted_at", "updated_at"])
            item_dal.invalidate_item_cache(item.branch_id, item.category_id, item.id)
        return item


class ExtraBusinessLogicLayer:

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
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        if extra_dal.extra_exists(branch_id, name):
            raise ExtraAlreadyExistsException()

        if group_id is not None:
            group = extra_group_dal.get_extra_group_by_id(group_id, branch_id)
            if group is None:
                raise ExtraGroupNotFoundException()

        return extra_dal.create_extra(
            branch_id=branch_id,
            name=name,
            price=price,
            available=available,
            group_id=group_id,
            description=description,
            order=order,
        )

    @staticmethod
    def update_extra(
        extra_id,
        branch_id,
        name: str | None = None,
        price: float | None = None,
        available: bool | None = None,
        group_id=None,
        group_id_provided: bool = False,
        description: str | None = None,
        order: int | None = None,
    ) -> Extra:
        extra = extra_dal.get_extra_by_id(extra_id, branch_id)
        if extra is None:
            raise ExtraNotFoundException()

        if name is not None and extra_dal.extra_exists(
            branch_id=branch_id, name=name, exclude_id=extra_id
        ):
            raise ExtraAlreadyExistsException()

        if group_id_provided and group_id is not None:
            group = extra_group_dal.get_extra_group_by_id(group_id, branch_id)
            if group is None:
                raise ExtraGroupNotFoundException()

        return extra_dal.update_extra(
            extra=extra,
            name=name,
            price=price,
            available=available,
            group_id=group_id,
            group_id_provided=group_id_provided,
            description=description,
            order=order,
        )

    @staticmethod
    def get_extra_list(branch_id, group_id=None):
        return extra_dal.get_all_extras(branch_id=branch_id, group_id=group_id)

    @staticmethod
    def get_extra_detail(extra_id, branch_id) -> Extra:
        extra = extra_dal.get_extra_by_id(extra_id, branch_id)
        if extra is None:
            raise ExtraNotFoundException()
        return extra

    @staticmethod
    def delete_extra(extra_id, branch_id) -> None:
        extra = extra_dal.get_extra_by_id(extra_id, branch_id)
        if extra is None:
            raise ExtraNotFoundException()
        extra_dal.delete_extra(extra)


class MenuItemExtraBusinessLogicLayer:

    @staticmethod
    def create_item_extra(
        item_id,
        branch_id,
        extra_id,
        price_override: float | None = None,
    ) -> MenuItemExtra:
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()

        extra = item_extra_dal.get_extra_by_id_and_branch(extra_id, branch_id)
        if extra is None:
            raise ExtraNotFoundException()

        if item_extra_dal.link_exists(item_id, extra_id):
            raise MenuItemExtraAlreadyExistsException()

        return item_extra_dal.create_link(
            item_id=item_id,
            extra_id=extra_id,
            price_override=price_override,
        )

    @staticmethod
    def update_item_extra(
        item_id,
        branch_id,
        extra_id,
        price_override: float | None = None,
        price_override_provided: bool = False,
    ) -> MenuItemExtra:
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()

        link = item_extra_dal.get_link(item_id, extra_id)
        if link is None:
            raise MenuItemExtraNotFoundException()

        return item_extra_dal.update_link(
            link=link,
            price_override=price_override,
            price_override_provided=price_override_provided,
        )

    @staticmethod
    def get_item_extra_list(item_id, branch_id):
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()
        return item_extra_dal.get_all_links(item_id=item_id)

    @staticmethod
    def delete_item_extra(item_id, branch_id, extra_id) -> None:
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()

        link = item_extra_dal.get_link(item_id, extra_id)
        if link is None:
            raise MenuItemExtraNotFoundException()

        item_extra_dal.delete_link(link)


class MenuItemExtraGroupBusinessLogicLayer:

    @staticmethod
    @transaction.atomic
    def assign_extra_groups_to_item(
        item_id,
        branch_id,
        group_ids: list,
    ) -> MenuItem:
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()

        if group_ids:
            groups = extra_group_dal.get_groups_by_ids(group_ids, branch_id)
            found_ids = {g.id for g in groups}
            missing = set(group_ids) - found_ids
            if missing:
                raise ExtraGroupNotFoundException()

            inactive = [g for g in groups if not g.is_active]
            if inactive:
                raise ExtraGroupNotActiveException()

        extra_group_dal.replace_item_extra_groups(item_id, group_ids)
        MenuItemExtraGroupDataAccessLayer.sync_item_extras_from_groups(
            item_id, branch_id
        )

        item_dal.invalidate_item_cache(
            item.branch_id, item.category_id, item.id
        )
        return item

    @staticmethod
    def get_item_extra_group_ids(item_id, branch_id) -> list:
        item = item_extra_dal.get_item_by_id_and_branch(item_id, branch_id)
        if item is None:
            raise MenuItemNotFoundException()
        return extra_group_dal.get_item_extra_group_ids(item_id)
