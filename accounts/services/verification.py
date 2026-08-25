from accounts.models import User, OTPType
from accounts.selectors import UserDataAccessLayer
from core.exceptions.account import (
    PhoneAlreadyVerifiedException,
    EmailAlreadyVerifiedException,
    PhoneAlreadyExistsException,
    EmailAlreadyExistsException,
)
from accounts.services import OTPBusinessLogiclayer

user_dal = UserDataAccessLayer()
otp_bll = OTPBusinessLogiclayer()

REQUIRED_PROFILE_FIELDS = ("first_name", "last_name", "phone_number", "email")


class PhoneVerificationBusinessLogicLayer:

    @classmethod
    def request_verification(cls, user: User, country_code: str, phone_number: str) -> None:
        if user.phone_number:
            raise PhoneAlreadyVerifiedException()

        full_phone = f"{country_code}{phone_number}"
        if user_dal.exists_by_phone(full_phone, exclude_user_id=user.id):
            raise PhoneAlreadyExistsException()

        otp_bll.generate(identifier=full_phone, otp_type=OTPType.VERIFY_PHONE)

    @classmethod
    def confirm_verification(cls, user: User, country_code: str, phone_number: str, code: str) -> User:
        if user.phone_number:
            raise PhoneAlreadyVerifiedException()

        full_phone = f"{country_code}{phone_number}"
        if user_dal.exists_by_phone(full_phone, exclude_user_id=user.id):
            raise PhoneAlreadyExistsException()

        otp_bll.verify(identifier=full_phone, code=code, otp_type=OTPType.VERIFY_PHONE)

        user.phone_number = full_phone
        user.country_code = country_code
        user.save(update_fields=["phone_number", "country_code"])
        return user


class EmailVerificationBusinessLogicLayer:

    @classmethod
    def request_verification(cls, user: User, email: str) -> None:
        if user.email:
            raise EmailAlreadyVerifiedException()

        if user_dal.exists_by_email(email, exclude_user_id=user.id):
            raise EmailAlreadyExistsException()

        otp_bll.generate(identifier=email, otp_type=OTPType.VERIFY_EMAIL)

    @classmethod
    def confirm_verification(cls, user: User, email: str, code: str) -> User:
        if user.email:
            raise EmailAlreadyVerifiedException()

        if user_dal.exists_by_email(email, exclude_user_id=user.id):
            raise EmailAlreadyExistsException()

        otp_bll.verify(identifier=email, code=code, otp_type=OTPType.VERIFY_EMAIL)

        user.email = email
        user.save(update_fields=["email"])
        return user


class AccountVerificationBusinessLogicLayer:

    @classmethod
    def verify_account(cls, user: User) -> tuple[bool, list[str]]:
        missing = [field for field in REQUIRED_PROFILE_FIELDS if not getattr(user, field)]

        if missing:
            return False, missing

        user.is_verified = True
        user.save(update_fields=["is_verified"])
        return True, []
