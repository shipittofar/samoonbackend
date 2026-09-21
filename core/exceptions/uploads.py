from core.exceptions import BaseAppException


class UploadValidationException(BaseAppException):
    status_code = 400
    code = "upload_validation_error"
    message = "Upload request is invalid."


class UploadNotFoundException(BaseAppException):
    status_code = 404
    code = "upload_not_found"
    message = "Upload asset was not found."


class UploadPermissionDeniedException(BaseAppException):
    status_code = 403
    code = "upload_permission_denied"
    message = "You do not have permission to perform this upload action."


class UploadConflictException(BaseAppException):
    status_code = 409
    code = "upload_conflict"
    message = "Conflicting upload input."


class UploadStateException(BaseAppException):
    status_code = 409
    code = "upload_invalid_state"
    message = "This upload cannot transition to the requested state."


class UploadObjectMissingException(BaseAppException):
    status_code = 400
    code = "upload_object_missing"
    message = "Uploaded object was not found in storage."


class UploadExpiredException(BaseAppException):
    status_code = 409
    code = "upload_expired"
    message = "This upload intent has expired."
