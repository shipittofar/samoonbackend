"""Deny-by-default API permissions, sign-out-everywhere on password change /
reset, and a forgot-password flow that does not reveal registered numbers."""

import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import OTPCode, OTPType, User

PASSWORD = "SecurePass123!"
NEW_PASSWORD = "AnotherPass456!"


def make_user(**kwargs):
    phone_local = f"912{uuid.uuid4().int % 10**7:07d}"
    defaults = {
        "first_name": "Test",
        "phone_number": f"+98{phone_local}",
        "country_code": "+98",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password(PASSWORD)
    user.save()
    return user


def local(user):
    return user.phone_number.removeprefix(user.country_code)


def old_access_token(user, seconds_ago=30):
    token = AccessToken.for_user(user)
    token.set_iat(at_time=timezone.now() - timedelta(seconds=seconds_ago))
    return str(token)


class DenyByDefaultTests(TestCase):
    def test_default_permission_is_authenticated(self):
        self.assertEqual(list(api_settings.DEFAULT_PERMISSION_CLASSES), [IsAuthenticated])

    def test_public_endpoints_stay_public(self):
        client = APIClient()
        self.assertEqual(client.get("/api/core/health/").status_code, 200)
        self.assertEqual(client.get("/api/core/geo/country/").status_code, 200)
        self.assertNotIn(client.get("/api/menu/items/featured/").status_code, (401, 403))  # 400 = needs a branch
        self.assertNotIn(client.get("/api/tenants/branches/").status_code, (401, 403))


class ChangePasswordRevokesSessionsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other_device = RefreshToken.for_user(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access_token(self.user)}")

    def change(self):
        return self.client.post(
            "/api/auth/change-password/",
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            format="json",
        )

    def test_returns_fresh_tokens_that_work(self):
        res = self.change()
        self.assertEqual(res.status_code, 200, res.data)
        fresh = APIClient()
        fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        self.assertEqual(fresh.get("/api/auth/me/").status_code, 200)

    def test_old_access_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.change()
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_other_devices_cannot_refresh(self):
        self.change()
        res = APIClient().post("/api/auth/token/refresh/", {"refresh": str(self.other_device)}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_old_token_rejected_on_websocket(self):
        from asgiref.sync import async_to_sync
        from core.middleware.websocket_auth import get_user_from_token

        token = old_access_token(self.user)
        self.assertEqual(async_to_sync(get_user_from_token)(token), self.user)
        self.change()
        self.assertFalse(async_to_sync(get_user_from_token)(token).is_authenticated)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class ForgotPasswordTests(TestCase):
    URL_REQ = "/api/auth/forget-password/request/"
    URL_CONFIRM = "/api/auth/forget-password/confirm/"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # the per-IP throttle
        self.client = APIClient()

    def request_reset(self, local_number):
        return self.client.post(self.URL_REQ, {"country_code": "+98", "phone_number": local_number}, format="json")

    def confirm(self, local_number, code):
        return self.client.post(
            self.URL_CONFIRM,
            {
                "country_code": "+98",
                "phone_number": local_number,
                "code": code,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            format="json",
        )

    def test_same_answer_for_registered_unknown_and_disabled_numbers(self):
        user = make_user()
        disabled = make_user(is_active=False)
        answers = {
            self.request_reset(local(user)).status_code,
            self.request_reset("9120000001").status_code,
            self.request_reset(local(disabled)).status_code,
        }
        self.assertEqual(answers, {204})
        self.assertTrue(OTPCode.objects.filter(identifier=user.phone_number).exists())
        self.assertFalse(OTPCode.objects.filter(identifier=disabled.phone_number).exists())
        self.assertFalse(OTPCode.objects.filter(identifier="+989120000001").exists())

    def test_code_limit_is_not_revealed(self):
        user = make_user()
        for _ in range(5):
            self.assertEqual(self.request_reset(local(user)).status_code, 204)

    def test_confirm_unknown_number_looks_like_wrong_code(self):
        user = make_user()
        self.request_reset(local(user))
        wrong = self.confirm(local(user), "000000")
        unknown = self.confirm("9120000002", "000000")
        self.assertEqual(wrong.status_code, unknown.status_code)
        self.assertEqual(wrong.data, unknown.data)

    def test_successful_reset_signs_out_everywhere(self):
        user = make_user()
        stale = old_access_token(user)
        self.request_reset(local(user))
        code = OTPCode.objects.filter(identifier=user.phone_number, otp_type=OTPType.FORGET_PASSWORD).latest("created_at").code
        self.assertEqual(self.confirm(local(user), code).status_code, 204)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PASSWORD))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {stale}")
        self.assertEqual(c.get("/api/auth/me/").status_code, 401)
