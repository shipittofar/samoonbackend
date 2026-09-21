from core.exceptions import BaseAppException


class CategoryAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "category_already_exists"
    message = "A category with this name already exists for this place."

class CategoryHasItemsException(BaseAppException):
    status_code = 400
    code = "category_has_items"
    message = "Cannot delete a category that still has menu items."