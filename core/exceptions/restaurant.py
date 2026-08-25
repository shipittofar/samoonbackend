# core/exceptions/menu.py

from core.exceptions import BaseAppException


class TenantNotFoundException(
    BaseAppException
):

    status_code = 404

    code = "tenant_not_found"

    message = "tenant not found."


class TenantSlugAlreadyExistsException(
    BaseAppException
):

    status_code = 400

    code = "tenant_slug_exists"

    message = "A tenant with this slug already exists."