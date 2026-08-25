from core.exceptions import BaseAppException


class OTPExpiredException(BaseAppException):
    status_code = 400
    code = "otp_expired"
    message = "OTP code has expired."


class OTPInvalidException(BaseAppException):
    status_code = 400
    code = "otp_invalid"
    message = "OTP code is invalid."


class OTPAlreadyUsedException(BaseAppException):
    status_code = 400
    code = "otp_already_used"
    message = "OTP code has already been used."


class UserInactiveException(BaseAppException):
    status_code = 403
    code = "user_inactive"
    message = "This account is inactive."


class PhoneNumberInvalidException(BaseAppException):
    status_code = 400
    code = "phone_invalid"
    message = "Phone number format is invalid."


class InvalidCredentialsException(BaseAppException):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid credentials."


class PasswordNotSetException(BaseAppException):
    status_code = 400
    code = "password_not_set"
    message = "Password has not been set for this account."


class PasswordAlreadySetException(BaseAppException):
    status_code = 400
    code = "password_already_set"
    message = "Password has already been set for this account."


class PhoneAlreadyVerifiedException(BaseAppException):
    status_code = 400
    code = "phone_already_verified"
    message = "Your phone number has already been verified."


class EmailAlreadyVerifiedException(BaseAppException):
    status_code = 400
    code = "email_already_verified"
    message = "Your email has already been verified."


class PhoneAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "phone_already_exists"
    message = "This phone number is already used by another account."


class EmailAlreadyExistsException(BaseAppException):
    status_code = 400
    code = "email_already_exists"
    message = "This email is already used by another account."


class UserNotFoundException(BaseAppException):
    status_code = 404
    code = "user_not_found"
    message = "The requested user was not found."


class AvatarNotSetException(BaseAppException):
    status_code = 400
    code = "avatar_not_set"
    message = "User has no avatar to delete."


class AccountAlreadyDeletedException(BaseAppException):
    status_code = 400
    code = "account_already_deleted"
    message = "This account has already been deleted."


class IdentifierNotVerifiedException(BaseAppException):
    status_code = 403
    code = "identifier_not_verified"
    message = "The identifier has not been verified."


class UserAlreadyExistsException(BaseAppException):
    status_code = 409
    code = "user_already_exists"
    message = "A user with the provided identifier already exists."


class InvalidTokenException(BaseAppException):
    status_code = 401
    code = "invalid_token"
    message = "The provided token is invalid or has expired."


class OTPRequestLimitExceededException(BaseAppException):
    status_code = 429
    code = "otp_request_limit_exceeded"
    message = "Too many OTP requests. Please try again later."
