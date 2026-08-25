from django.db import transaction

from menu.models import MenuCategory
from menu.selectors import CategoryDataAccessLayer
from core.exceptions import (
    CategoryAlreadyExistsException,
    BranchNotFoundException,
    CategoryNotFoundException
)


category_dal = CategoryDataAccessLayer()


class CategoryBusinessLogicLayer:

    @staticmethod
    def create_menu_category(
        branch_id,
        name: str,
        description: str = "",
        image=None,
        sort_order: int = 0,
    ) -> MenuCategory:

        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        if category_dal.category_exists(branch_id, name):
            raise CategoryAlreadyExistsException()

        return category_dal.create_category(
            branch_id=branch_id,
            name=name,
            description=description,
            image=image,
            sort_order=sort_order,
        )

    @staticmethod
    @transaction.atomic
    def bulk_create_menu_categories(items: list[dict]) -> list[MenuCategory]:
        seen = set()
        for item in items:
            key = (item["branch_id"], item["name"])
            if key in seen:
                raise CategoryAlreadyExistsException()
            seen.add(key)

        branch_ids = {item["branch_id"] for item in items}
        missing_branches = category_dal.get_missing_branch_ids(branch_ids)
        if missing_branches:
            raise BranchNotFoundException()

        existing_pairs = category_dal.get_existing_category_pairs(
            [(item["branch_id"], item["name"]) for item in items]
        )
        if existing_pairs:
            raise CategoryAlreadyExistsException()

        return category_dal.bulk_create_categories(items)

    @staticmethod
    def update_menu_category(
        branch_id,
        category_id,
        name: str | None = None,
        description: str | None = None,
        image=None,
        image_provided: bool = False,
        sort_order: int | None = None,
    ) -> MenuCategory:
        category = category_dal.get_menu_category_by_id(
            category_id=category_id, branch_id=branch_id)
        if category is None:
            raise CategoryNotFoundException()

        if name is not None and category_dal.category_exists(
                branch_id=category.branch_id,
                name=name,
                exclude_id=category_id,
        ):
            raise CategoryAlreadyExistsException()

        return category_dal.update_category(
            category=category,
            name=name,
            description=description,
            image=image,
            image_provided=image_provided,
            sort_order=sort_order,
        )

    @staticmethod
    def get_category_list(branch_id):
        return category_dal.get_all_categories(branch_id=branch_id)

    @staticmethod
    def get_category_detail(category_id, branch_id) -> MenuCategory:
        category = category_dal.get_menu_category_by_id(
            category_id, branch_id=branch_id)
        if category is None:
            raise CategoryNotFoundException()
        return category

    @staticmethod
    def delete_menu_category(
        category_id,
        branch_id,
    ) -> None:
        category = category_dal.get_menu_category_by_id(
            category_id=category_id,
            branch_id=branch_id,
        )
        if category is None:
            raise CategoryNotFoundException()

        category_dal.delete_category(category)

    @staticmethod
    def get_all_categories():
        return category_dal.get_all_categories_unfiltered()

    @staticmethod
    def get_console_categories(user):
        return category_dal.get_categories_by_owner(user)

    @staticmethod
    def get_console_category_detail(category_id, user) -> MenuCategory:
        category = category_dal.get_category_by_id_for_owner(category_id, user)
        if category is None:
            raise CategoryNotFoundException()
        return category

    @staticmethod
    def get_console_categoryies_detail_by_branch(branch_id, user) -> MenuCategory:
        category = category_dal.get_categories_by_owner_branch(branch_id, user)
        if category is None:
            raise CategoryNotFoundException()
        return category

    @staticmethod
    def get_console_categories_by_tenant_branch(user, tenant_id, branch_id):
        if not category_dal.branch_belongs_to_owner(
            branch_id=branch_id,
            tenant_id=tenant_id,
            user=user,
        ):
            raise BranchNotFoundException()

        return category_dal.get_categories_by_owner_tenant_branch(
            user=user,
            tenant_id=tenant_id,
            branch_id=branch_id,
        )
