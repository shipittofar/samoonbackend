from menu.models import Extra, ExtraGroup
from menu.selectors import CategoryDataAccessLayer, ExtraGroupDataAccessLayer
from core.exceptions import (
    BranchNotFoundException,
    ExtraGroupNotFoundException,
    ExtraGroupAlreadyExistsException,
    ExtraGroupValidationException,
)

category_dal = CategoryDataAccessLayer()
extra_group_dal = ExtraGroupDataAccessLayer()


class ExtraGroupBusinessLogicLayer:

    @staticmethod
    def _validate_selection_rules(
        selection_type: str,
        required: bool,
        min_selection: int,
        max_selection: int,
    ) -> None:
        if min_selection < 0:
            raise ExtraGroupValidationException(
                "min_selection must be greater than or equal to 0."
            )
        if max_selection < 1:
            raise ExtraGroupValidationException(
                "max_selection must be greater than or equal to 1."
            )
        if min_selection > max_selection:
            raise ExtraGroupValidationException(
                "min_selection must be less than or equal to max_selection."
            )
        if required and min_selection < 1:
            raise ExtraGroupValidationException(
                "Required groups must have min_selection >= 1."
            )
        if selection_type == "single":
            if max_selection != 1:
                raise ExtraGroupValidationException(
                    "Single-selection groups must have max_selection == 1."
                )
            if min_selection not in (0, 1):
                raise ExtraGroupValidationException(
                    "Single-selection groups must have min_selection of 0 or 1."
                )

    @staticmethod
    def create_extra_group(
        branch_id,
        name: str,
        selection_type: str = "multiple",
        required: bool = False,
        min_selection: int = 0,
        max_selection: int = 1,
        order: int = 0,
        is_active: bool = True,
        description: str = "",
    ) -> ExtraGroup:
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        if extra_group_dal.extra_group_exists(branch_id, name):
            raise ExtraGroupAlreadyExistsException()

        ExtraGroupBusinessLogicLayer._validate_selection_rules(
            selection_type=selection_type,
            required=required,
            min_selection=min_selection,
            max_selection=max_selection,
        )

        return extra_group_dal.create_extra_group(
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

    @staticmethod
    def update_extra_group(
        group_id,
        branch_id,
        name: str | None = None,
        description: str | None = None,
        selection_type: str | None = None,
        required: bool | None = None,
        min_selection: int | None = None,
        max_selection: int | None = None,
        order: int | None = None,
        is_active: bool | None = None,
    ) -> ExtraGroup:
        group = extra_group_dal.get_extra_group_by_id(group_id, branch_id)
        if group is None:
            raise ExtraGroupNotFoundException()

        if name is not None and extra_group_dal.extra_group_exists(
            branch_id=branch_id, name=name, exclude_id=group_id
        ):
            raise ExtraGroupAlreadyExistsException()

        resolved_selection_type = (
            selection_type if selection_type is not None else group.selection_type
        )
        resolved_required = required if required is not None else group.required
        resolved_min = (
            min_selection if min_selection is not None else group.min_selection
        )
        resolved_max = (
            max_selection if max_selection is not None else group.max_selection
        )

        ExtraGroupBusinessLogicLayer._validate_selection_rules(
            selection_type=resolved_selection_type,
            required=resolved_required,
            min_selection=resolved_min,
            max_selection=resolved_max,
        )

        updated = extra_group_dal.update_extra_group(
            group=group,
            name=name,
            description=description,
            selection_type=selection_type,
            required=required,
            min_selection=min_selection,
            max_selection=max_selection,
            order=order,
            is_active=is_active,
        )

        if is_active is not None or selection_type is not None:
            from menu.selectors.extra_group_dal import MenuItemExtraGroupDataAccessLayer
            MenuItemExtraGroupDataAccessLayer.sync_items_for_group(
                group_id, branch_id
            )

        return updated

    @staticmethod
    def get_extra_group_list(branch_id):
        return extra_group_dal.get_all_extra_groups(branch_id=branch_id)

    @staticmethod
    def get_extra_group_list_for_console(branch_id):
        return extra_group_dal.get_all_extra_groups_for_console(branch_id=branch_id)

    @staticmethod
    def get_extra_group_detail(group_id, branch_id) -> ExtraGroup:
        group = extra_group_dal.get_extra_group_by_id(group_id, branch_id)
        if group is None:
            raise ExtraGroupNotFoundException()
        return group

    @staticmethod
    def delete_extra_group(group_id, branch_id) -> None:
        group = extra_group_dal.get_extra_group_by_id(group_id, branch_id)
        if group is None:
            raise ExtraGroupNotFoundException()
        extra_group_dal.delete_extra_group(group)

    @staticmethod
    def reorder_extra_groups(branch_id, ordered_ids: list) -> list[ExtraGroup]:
        if not category_dal.branch_exists(branch_id):
            raise BranchNotFoundException()

        existing_ids = {
            g.id for g in extra_group_dal.get_all_extra_groups(branch_id)
        }
        if set(ordered_ids) != existing_ids:
            raise ExtraGroupValidationException(
                "order must contain every extra group id for this branch exactly once."
            )

        return extra_group_dal.reorder_extra_groups(branch_id, ordered_ids)
