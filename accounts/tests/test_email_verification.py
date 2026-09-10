"""Tests for email confirmation vs account-level verification."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import OTPCode, OTPType, User


CONFIRM_EMAIL_URL = "/api/auth/verify-email/confirm/"
VERIFY_ACCOUNT_URL = "/api/auth/verify-account/"
VALID_CODE = "123456"
NEW_EMAIL = "user@example.com"


def make_user(*, with_email=False, is_verified=False, **kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "first_name": "John",
        "last_name": "Doe",
        "phone_number": f"+98912{uuid.uuid4().int % 10**7:07d}",
        "country_code": "+98",
        "is_verified": is_verified,
    }
    if with_email:
        defaults["email"] = f"{uuid.uuid4().hex}@example.com"
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_unusable_password()
    user.save()
    return user


def make_email_otp(identifier, *, code=VALID_CODE, expired=False, is_used=False):
    expires_at = timezone.now() + timedelta(minutes=2)
    if expired:
        expires_at = timezone.now() - timedelta(seconds=5)
    return OTPCode.objects.create(
        identifier=identifier,
        otp_type=OTPType.VERIFY_EMAIL,
        code=code,
        expires_at=expires_at,
        is_used=is_used,
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class ConfirmEmailVerificationTests(TestCase):
    def test_successful_email_confirmation_returns_user_with_email(self):
        user = make_user(with_email=False, is_verified=False)
        otp = make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], NEW_EMAIL)

        user.refresh_from_db()
        self.assertEqual(user.email, NEW_EMAIL)

        otp.refresh_from_db()
        self.assertTrue(otp.is_used)

    def test_successful_confirmation_does_not_set_is_verified(self):
        user = make_user(with_email=False, is_verified=False)
        make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_verified"])

        user.refresh_from_db()
        self.assertFalse(user.is_verified)

    def test_already_assigned_email_returns_email_already_verified(self):
        existing_email = "already@example.com"
        user = make_user(email=existing_email, is_verified=False)
        make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "email_already_verified")
        self.assertEqual(
            response.data["error"]["message"],
            "Your email has already been verified.",
        )

        user.refresh_from_db()
        self.assertEqual(user.email, existing_email)

    def test_duplicate_email_returns_email_already_exists(self):
        make_user(email=NEW_EMAIL)
        user = make_user(with_email=False)
        make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "email_already_exists")
        self.assertEqual(
            response.data["error"]["message"],
            "This email is already used by another account.",
        )

        user.refresh_from_db()
        self.assertIsNone(user.email)

    def test_invalid_otp_does_not_change_email(self):
        user = make_user(with_email=False)
        otp = make_email_otp(NEW_EMAIL, code=VALID_CODE)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": "654321"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "otp_invalid")
        self.assertEqual(response.data["error"]["message"], "OTP code is invalid.")

        user.refresh_from_db()
        self.assertIsNone(user.email)

        otp.refresh_from_db()
        self.assertFalse(otp.is_used)
        self.assertEqual(otp.attempts, 1)

    def test_expired_otp_does_not_change_email(self):
        user = make_user(with_email=False)
        otp = make_email_otp(NEW_EMAIL, expired=True)
        client = auth_client(user)

        response = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "otp_expired")
        self.assertEqual(response.data["error"]["message"], "OTP code has expired.")

        user.refresh_from_db()
        self.assertIsNone(user.email)

        otp.refresh_from_db()
        self.assertFalse(otp.is_used)

    def test_otp_is_marked_used_after_success(self):
        user = make_user(with_email=False)
        otp = make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )

        otp.refresh_from_db()
        self.assertTrue(otp.is_used)


class VerifyAccountSeparationTests(TestCase):
    def test_verify_account_sets_is_verified_when_profile_is_complete(self):
        user = make_user(
            email="complete@example.com",
            first_name="John",
            last_name="Doe",
            is_verified=False,
        )
        self.assertTrue(user.email)
        self.assertTrue(user.first_name)
        self.assertTrue(user.last_name)
        self.assertTrue(user.phone_number)
        self.assertFalse(user.is_verified)

        client = auth_client(user)
        response = client.post(VERIFY_ACCOUNT_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_verified"])
        self.assertEqual(response.data["missing_fields"], [])

        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_complete_profile_after_email_confirm_still_requires_verify_account(self):
        user = make_user(with_email=False, is_verified=False)
        make_email_otp(NEW_EMAIL)
        client = auth_client(user)

        confirm = client.post(
            CONFIRM_EMAIL_URL,
            {"email": NEW_EMAIL, "code": VALID_CODE},
            format="json",
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertFalse(confirm.data["is_verified"])

        user.refresh_from_db()
        self.assertEqual(user.email, NEW_EMAIL)
        self.assertFalse(user.is_verified)

        verify = client.post(VERIFY_ACCOUNT_URL, {}, format="json")
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        self.assertTrue(verify.data["is_verified"])

        user.refresh_from_db()
        self.assertTrue(user.is_verified)
