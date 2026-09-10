import secrets
from datetime import timedelta
from django.utils import timezone
from accounts.models import OTPCode
from accounts.selectors import UserDataAccessLayer
from core.exceptions import (
    OTPInvalidException,
    OTPExpiredException,
    OTPAlreadyUsedException,
    OTPRequestLimitExceededException,
)

user_dal = UserDataAccessLayer()


class OTPBusinessLogiclayer:

    OTP_LENGTH = 6
    OTP_EXPIRY_MINUTES = 2
    MAX_ATTEMPTS = OTPCode.MAX_ATTEMPTS

    RATE_LIMIT_WINDOW_MINUTES = 15
    RATE_LIMIT_MAX_REQUESTS = 3

    @classmethod
    def generate(cls, identifier: str, otp_type: str) -> OTPCode:
        window_start = timezone.now() - timedelta(minutes=cls.RATE_LIMIT_WINDOW_MINUTES)
        recent_requests = user_dal.count_recent_otp_requests(identifier, since=window_start)
        if recent_requests >= cls.RATE_LIMIT_MAX_REQUESTS:
            raise OTPRequestLimitExceededException()

        OTPCode.objects.filter(
            identifier=identifier,
            otp_type=otp_type,
            is_used=False,
        ).update(is_used=True)

        code = cls._generate_code()
        expires_at = timezone.now() + timedelta(minutes=cls.OTP_EXPIRY_MINUTES)

        return OTPCode.objects.create(
            identifier=identifier,
            otp_type=otp_type,
            code=code,
            expires_at=expires_at,
        )

    @classmethod
    def verify(
        cls,
        identifier: str,
        code: str,
        otp_type: str,
        *,
        commit_success: bool = True,
    ) -> OTPCode:
        otp = user_dal.get_latest_active_otp(identifier, otp_type=otp_type)

        if otp is None:
            raise OTPInvalidException()

        if otp.is_used:
            raise OTPAlreadyUsedException()

        if otp.is_expired():
            raise OTPExpiredException()

        if not otp.has_attempts_left():
            otp.is_used = True
            otp.save(update_fields=["is_used"])
            raise OTPExpiredException()

        if otp.code != code:
            otp.attempts += 1
            attempts_exhausted = not otp.has_attempts_left()
            if attempts_exhausted:
                otp.is_used = True
                otp.save(update_fields=["attempts", "is_used"])
                raise OTPExpiredException()

            otp.save(update_fields=["attempts"])
            raise OTPInvalidException()

        otp.is_used = True
        if commit_success:
            otp.save(update_fields=["is_used"])
        return otp

    @classmethod
    def _generate_code(cls) -> str:
        lower_bound = 10 ** (cls.OTP_LENGTH - 1)
        upper_bound = (10 ** cls.OTP_LENGTH) - 1
        return str(secrets.randbelow(upper_bound - lower_bound + 1) + lower_bound)
