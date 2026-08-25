from core.exceptions import BaseAppException


class CategoryAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "category_already_exists"
    message = "A category with this name already exists for this place."

class CategoryNotFoundException(BaseAppException):
    status_code = 404
    code = "category_not_found"
    message = "Category not found."