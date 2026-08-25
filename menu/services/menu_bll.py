from menu.selectors.menu_dal import MenuDataAccessLayer
from menu.selectors import CategoryDataAccessLayer
from core.exceptions import BranchNotFoundException
from tenants.api.serializers.response.tenant_summary import (
    TenantSummarySerializer,
    build_tenant_summary,
)
from tenants.models import Branch


menu_dal = MenuDataAccessLayer()
category_dal = CategoryDataAccessLayer()


class MenuBusinessLogicLayer:

    @staticmethod
    def _assert_branch_exists(branch_id) -> None:
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

    @staticmethod
    def get_categories_with_items(branch_id, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_categories_with_items(branch_id, tags=tags)

    @staticmethod
    def get_popular_items(branch_id, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_popular_items(branch_id, tags=tags)

    @staticmethod
    def get_featured_items(branch_id, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_featured_items(branch_id, tags=tags)

    @staticmethod
    def get_active_items(branch_id, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_active_items(branch_id, tags=tags)

    @staticmethod
    def get_items_by_price(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_items_by_price(
            branch_id=branch_id,
            min_value=min_value,
            max_value=max_value,
            order=order,
            tags=tags,
        )

    @staticmethod
    def get_items_by_preparation_time(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_items_by_preparation_time(
            branch_id=branch_id,
            min_value=min_value,
            max_value=max_value,
            order=order,
            tags=tags,
        )

    @staticmethod
    def get_items_by_calories(
        branch_id, min_value=None, max_value=None, order=None, *, tags=None
    ):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_items_by_calories(
            branch_id=branch_id,
            min_value=min_value,
            max_value=max_value,
            order=order,
            tags=tags,
        )

    @staticmethod
    def get_items_by_discount(
        branch_id,
        has_discount=None,
        min_value=None,
        max_value=None,
        order=None,
        *,
        tags=None,
    ):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_items_by_discount(
            branch_id=branch_id,
            has_discount=has_discount,
            min_value=min_value,
            max_value=max_value,
            order=order,
            tags=tags,
        )

    @staticmethod
    def get_branch_tenant_summary(branch_id):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        branch = (
            Branch.objects.select_related("tenant")
            .filter(pk=branch_id)
            .first()
        )
        tenant_summary = None
        if branch is not None:
            summary = build_tenant_summary(branch.tenant)
            if summary is not None:
                tenant_summary = TenantSummarySerializer(summary).data
        return {"tenant": tenant_summary}

    @staticmethod
    def get_categories_with_items_summary(branch_id):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        summary = MenuBusinessLogicLayer.get_branch_tenant_summary(branch_id)
        return {
            "category_count": menu_dal.get_categories_count(branch_id),
            "item_count": menu_dal.get_items_count(branch_id),
            **summary,
        }

    @staticmethod
    def filter_items(branch_id, **filters):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.filter_items(branch_id, **filters)

    @staticmethod
    def search_items(branch_id, query: str, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.search_items(branch_id, query, tags=tags)

    @staticmethod
    def get_related_items(branch_id, item_id, *, tags=None):
        MenuBusinessLogicLayer._assert_branch_exists(branch_id)
        return menu_dal.get_related_items(branch_id, item_id, tags=tags)
