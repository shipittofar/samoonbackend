"""Tests for password-login endpoint (/api/auth/password-login/)."""

import uuid

from django.contrib.auth.hashers import identify_hasher
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User


PASSWORD_LOGIN_URL = "/api/auth/password-login/"
TEST_PASSWORD = "SecurePass123!"


def make_user(*, with_phone=True, with_email=True, password=TEST_PASSWORD, **kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "first_name": "Test",
        "last_name": "User",
    }
    if with_phone:
        defaults["phone_number"] = f"+98912{uuid.uuid4().int % 10**7:07d}"
        defaults["country_code"] = "+98"
    if with_email:
        defaults["email"] = f"{uuid.uuid4().hex}@example.com"
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password(password)
    user.save()
    return user


class PasswordLoginValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_phone_only_login_success(self):
        user = make_user(with_email=False)
        local_phone = user.phone_number.removeprefix(user.country_code)

        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {
                "country_code": user.country_code,
                "phone_number": local_phone,
                "password": TEST_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_email_only_login_success(self):
        user = make_user(with_phone=False)

        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"email": user.email, "password": TEST_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_email_login_normalizes_input(self):
        user = make_user(with_phone=False)

        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"email": f"  {user.email.upper()}  ", "password": TEST_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_missing_identifier_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"password": TEST_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_phone_without_prefix_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"phone_number": "9123456789", "password": TEST_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_without_password_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"email": "user@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_email_format_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {"email": "not-an-email", "password": TEST_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_phone_format_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {
                "country_code": "+98",
                "phone_number": "abc123",
                "password": TEST_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_country_code_format_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {
                "country_code": "98",
                "phone_number": "9123456789",
                "password": TEST_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_both_email_and_phone_returns_validation_error(self):
        response = self.client.post(
            PASSWORD_LOGIN_URL,
            {
                "email": "user@example.com",
                "country_code": "+98",
                "phone_number": "9123456789",
                "password": TEST_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PasswordLoginSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def _login(self, **payload):
        return self.client.post(PASSWORD_LOGIN_URL, payload, format="json")

    def test_wrong_password_returns_generic_authentication_error(self):
        local_phone = self.user.phone_number.removeprefix(self.user.country_code)

        response = self._login(
            country_code=self.user.country_code,
            phone_number=local_phone,
            password="wrong-password",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "invalid_credentials")
        self.assertEqual(response.data["error"]["message"], "Invalid credentials.")

    def test_nonexistent_phone_returns_generic_authentication_error(self):
        response = self._login(
            country_code="+98",
            phone_number="9120000000",
            password=TEST_PASSWORD,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "invalid_credentials")
        self.assertEqual(response.data["error"]["message"], "Invalid credentials.")

    def test_nonexistent_email_returns_generic_authentication_error(self):
        response = self._login(
            email="missing@example.com",
            password=TEST_PASSWORD,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "invalid_credentials")
        self.assertEqual(response.data["error"]["message"], "Invalid credentials.")

    def test_password_is_checked_via_django_hashing(self):
        self.assertTrue(self.user.check_password(TEST_PASSWORD))
        hasher = identify_hasher(self.user.password)
        self.assertNotEqual(hasher.algorithm, "plaintext")

    def test_user_without_password_returns_generic_authentication_error(self):
        user = make_user()
        user.set_unusable_password()
        user.save(update_fields=["password"])
        local_phone = user.phone_number.removeprefix(user.country_code)

        response = self._login(
            country_code=user.country_code,
            phone_number=local_phone,
            password=TEST_PASSWORD,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "invalid_credentials")
