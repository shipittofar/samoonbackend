from django.db.models import Q
from accounts.models import User, OTPCode


class UserDataAccessLayer:

    @staticmethod
    def get_by_phone(phone_number: str) -> User | None:
        return User.objects.filter(phone_number=phone_number).first()

    @staticmethod
    def get_by_email(email: str) -> User | None:
        return User.objects.filter(email=email).first()

    @staticmethod
    def get_by_identifier(identifier: str) -> User | None:
        return User.objects.filter(Q(phone_number=identifier) | Q(email=identifier)).first()

    @staticmethod
    def get_latest_active_otp(identifier: str, otp_type: str) -> OTPCode | None:
        return (
            OTPCode.objects.filter(
                identifier=identifier,
                otp_type=otp_type,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def count_recent_otp_requests(identifier: str, since) -> int:
        return OTPCode.objects.filter(identifier=identifier, created_at__gte=since).count()

    @staticmethod
    def get_by_id(user_id) -> User | None:
        return User.objects.filter(id=user_id).first()

    @staticmethod
    def list_all():
        return User.objects.all().order_by("-created_at")

    @staticmethod
    def exists_by_phone(phone_number: str, exclude_user_id=None) -> bool:
        qs = User.objects.filter(phone_number=phone_number)
        if exclude_user_id:
            qs = qs.exclude(id=exclude_user_id)
        return qs.exists()

    @staticmethod
    def exists_by_email(email: str, exclude_user_id=None) -> bool:
        qs = User.objects.filter(email=email)
        if exclude_user_id:
            qs = qs.exclude(id=exclude_user_id)
        return qs.exists()

    @staticmethod
    def has_verified_identifier(identifier: str, otp_type: str) -> bool:
        return OTPCode.objects.filter(identifier=identifier, otp_type=otp_type, is_used=True).exists()
