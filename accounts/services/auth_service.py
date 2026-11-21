from datetime import timedelta

from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from accounts.models import User, OTPType
from accounts.selectors import UserDataAccessLayer
from core.exceptions.account import (
    UserInactiveException,
    InvalidCredentialsException,
    PasswordAlreadySetException,
    PasswordNotSetException,
    UserNotFoundException,
    IdentifierNotVerifiedException,
    UserAlreadyExistsException,
    InvalidTokenException,
)
from accounts.services import OTPBusinessLogiclayer

user_dal = UserDataAccessLayer()
otp_bll = OTPBusinessLogiclayer()

# Sign-up must follow a successful OTP verification of the same identifier
# within this window; each verification can create one account only.
REGISTRATION_WINDOW = timedelta(minutes=15)


class AuthBusinessLogicLayer:

    @staticmethod
    def issue_tokens(user: User) -> dict:
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

    @staticmethod
    def register(
        identifier: str,
        is_email: bool,
        first_name: str,
        last_name: str = "",
        country_code: str | None = None,
    ) -> User:
        if user_dal.get_by_identifier(identifier):
            raise UserAlreadyExistsException()

        try:
            with transaction.atomic():
                # Spent inside the transaction: if account creation fails, the
                # verification is rolled back and can be used again.
                if not user_dal.consume_verified_identifier(
                    identifier,
                    otp_type=OTPType.LOGIN_SIGNUP,
                    max_age=REGISTRATION_WINDOW,
                ):
                    raise IdentifierNotVerifiedException()

                if is_email:
                    user = User.objects.create_user(
                        email=identifier,
                        first_name=first_name,
                        last_name=last_name,
                    )
                else:
                    user = User.objects.create_user(
                        phone_number=identifier,
                        country_code=country_code,
                        first_name=first_name,
                        last_name=last_name,
                    )
        except IntegrityError:
            # e.g. the identifier still belongs to a soft-deleted account.
            raise UserAlreadyExistsException()
        return user

    @staticmethod
    def logout(refresh_token: str) -> None:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            raise InvalidTokenException()


auth_service = AuthBusinessLogicLayer()


class PasswordAuthBusinessLogicLayer:

    @staticmethod
    def login(*, identifier: str, is_email: bool, password: str) -> dict:
        if is_email:
            user = user_dal.get_by_email(identifier)
        else:
            user = user_dal.get_by_phone(identifier)

        if user is None or not user.has_usable_password():
            raise InvalidCredentialsException()

        if not user.is_active:
            raise UserInactiveException()

        if not user.check_password(password):
            raise InvalidCredentialsException()

        return auth_service.issue_tokens(user)

    @staticmethod
    def set_password(user: User, password: str) -> None:
        if user.has_usable_password():
            raise PasswordAlreadySetException()

        user.set_password(password)
        user.save(update_fields=["password"])

    @staticmethod
    def change_password(user: User, old_password: str, new_password: str) -> None:
        if not user.has_usable_password():
            raise PasswordNotSetException()

        if not user.check_password(old_password):
            raise InvalidCredentialsException()

        user.set_password(new_password)
        user.save(update_fields=["password"])


class ForgetPasswordBusinessLogicLayer:

    @staticmethod
    def request_reset(phone_number: str) -> None:
        user = user_dal.get_by_phone(phone_number)
        if user is None:
            raise UserNotFoundException()
        if not user.is_active:
            raise UserInactiveException()

        otp_bll.generate(identifier=phone_number, otp_type=OTPType.FORGET_PASSWORD)

    @staticmethod
    def confirm_reset(phone_number: str, code: str, new_password: str) -> User:
        user = user_dal.get_by_phone(phone_number)
        if user is None:
            raise UserNotFoundException()
        if not user.is_active:
            raise UserInactiveException()

        otp_bll.verify(identifier=phone_number, code=code, otp_type=OTPType.FORGET_PASSWORD)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        return user
