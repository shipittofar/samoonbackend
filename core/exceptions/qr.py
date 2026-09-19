from core.exceptions import BaseAppException


class QrNotFoundException(BaseAppException):
    status_code = 404
    code = "qr_not_found"
    message = "QR code not found."


class QrDisabledException(BaseAppException):
    status_code = 410
    code = "qr_disabled"
    message = "This QR code is no longer active."


class QrAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "qr_already_exists"
    message = "An active QR code already exists for this entity."


class UnauthorizedQrAccessException(BaseAppException):
    status_code = 403
    code = "unauthorized_qr_access"
    message = "You do not have permission to manage this QR code."


class QrInvalidDestinationException(BaseAppException):
    status_code = 400
    code = "qr_invalid_destination"
    message = "Invalid QR destination type."
