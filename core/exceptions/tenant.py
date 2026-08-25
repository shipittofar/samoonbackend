# core/exceptions/menu.py

from core.exceptions import BaseAppException


class TenantNotFoundException(BaseAppException):
    status_code = 404
    code = "tenant_not_found"
    message = "tenant not found."


class TenantSlugAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "tenant_slug_exists"
    message = "A tenant with this slug already exists."


class BranchNotFoundException(BaseAppException):
    status_code = 400
    code = "branch_not_found"
    message = "branch not found."


class TenantPermissionDeniedException(BaseAppException):
    status_code = 403
    code = "tenant_permission_denied"
    message = "You do not have permission to modify this tenant."


class BranchPermissionDeniedException(BaseAppException):
    status_code = 403
    code = "branch_permission_denied"
    message = "You do not have permission to modify this branch."


class DuplicateTenantException(BaseAppException):
    status_code = 400
    code = "duplicate_tenant"
    message = "You already have a tenant with this name."


class DuplicateBranchException(BaseAppException):
    status_code = 400
    code = "duplicate_branch"
    message = "This tenant already has a branch with this name."


class AddressInUseException(BaseAppException):
    status_code = 409
    code = "address_in_use"
    message = "This address cannot be deleted because it is linked to one or more orders."


class ManagerNotFoundException(BaseAppException):
    status_code = 404
    code = "manager_not_found"
    message = "Manager not found."