import uuid
from django.db import models
from django.utils import timezone


class OTPType(models.TextChoices):
    LOGIN_SIGNUP = "login-signup", "Login / Signup"
    FORGET_PASSWORD = "forget-password", "Forget Password"
    VERIFY_PHONE = "verify-phone", "Verify Phone"
    VERIFY_EMAIL = "verify-email", "Verify Email"


class OTPCode(models.Model):
    MAX_ATTEMPTS = 3

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identifier = models.CharField(max_length=255, db_index=True)
    otp_type = models.CharField(max_length=32, choices=OTPType.choices)
    code = models.CharField(max_length=6)
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "otp_codes"

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def has_attempts_left(self) -> bool:
        return self.attempts < self.MAX_ATTEMPTS

    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired() and self.has_attempts_left()