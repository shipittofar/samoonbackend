# core/exceptions/menu.py
from core.exceptions import BaseAppException


class MenuItemAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "menu_item_already_exists"
    message = "A menu item with this name already exists in this category."


class MenuItemNotFoundException(BaseAppException):
    status_code = 404
    code = "menu_item_not_found"
    message = "Menu item not found."


class CategoryNotFoundException(BaseAppException):
    status_code = 404
    code = "category_not_found"
    message = "Category not found."

class TagNotFoundException(BaseAppException):
    status_code = 404
    code = "tag_not_found"
    message = "Tag not found."


class TagAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "tag_already_exists"
    message = "A tag with this name already exists in this branch."


class TagValidationException(BaseAppException):
    status_code = 400
    code = "tag_validation_error"
    message = "Tag validation failed."


class TagBranchMismatchException(BaseAppException):
    status_code = 400
    code = "tag_branch_mismatch"
    message = "One or more tags do not belong to this branch."

class ExtraNotFoundException(BaseAppException):
    status_code = 404
    code = "extera_not_found"
    message = "Extera not found."

class ExtraAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "extera_already_exists"
    message = "A extera with this name already exists in this place."

class MenuItemExtraAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "menu_item_extera_already_exists"
    message = "A menu item extera with this name already exists in this place."

class MenuItemExtraNotFoundException(BaseAppException):
    status_code = 404
    code = "menu_item_extera_not_found"
    message = "Menu Item Extera not found."


class ExtraGroupNotFoundException(BaseAppException):
    status_code = 404
    code = "extra_group_not_found"
    message = "Extra group not found."


class ExtraGroupAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "extra_group_already_exists"
    message = "An extra group with this name already exists in this branch."


class ExtraGroupValidationException(BaseAppException):
    status_code = 400
    code = "extra_group_validation_error"
    message = "Extra group validation failed."


class ExtraGroupNotActiveException(BaseAppException):
    status_code = 400
    code = "extra_group_not_active"
    message = "Inactive extra groups cannot be assigned to menu items."