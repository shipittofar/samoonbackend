from core.exceptions import BaseAppException


class AddressNotFoundException(BaseAppException):
    status_code = 404
    code = "address_not_found"
    message = "Address not found."


class DuplicateAddressException(BaseAppException):
    status_code = 409
    code = "duplicate_address"
    message = "This address already exists in your address book."


class AddressLimitExceededException(BaseAppException):
    status_code = 400
    code = "address_limit_exceeded"
    message = "Maximum number of saved addresses reached."


class AddressNotServiceableException(BaseAppException):
    status_code = 400
    code = "address_not_serviceable"
    message = "This address is outside the delivery service area."


class AddressPermissionDeniedException(BaseAppException):
    status_code = 403
    code = "address_permission_denied"
    message = "You do not have permission to access this address."
