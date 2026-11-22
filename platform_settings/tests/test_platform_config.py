from django.test import TestCase
from rest_framework.test import APIClient

from access.tests.helpers import make_tenant, make_user
from platform_settings.models import PlatformSetting, PlatformSettingChange

URL = "/api/platform/config/"
HISTORY = "/api/platform/config/history/"


class PlatformConfigApiTests(TestCase):
    def setUp(self):
        self.root = make_user(is_superuser=True, is_staff=True, first_name="Root", last_name="Admin")
        self.client = APIClient()

    def put(self, body, user=None):
        self.client.force_authenticate(user or self.root)
        return self.client.put(URL, body, format="json")

    def test_public_read_starts_empty_and_ignores_bad_tokens(self):
        anon = APIClient()
        anon.credentials(HTTP_AUTHORIZATION="Bearer expired.token.value")
        res = anon.get(URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"overrides": {}})

    def test_superuser_saves_and_everyone_reads(self):
        res = self.put({
            "changes": [
                {"fieldId": "authentication.max_login_attempts", "value": 7},
                {"fieldId": "languages.supported", "value": ["fa", "en"]},
                {"fieldId": "authentication.guest_checkout_enabled", "value": False},
            ],
            "reason": "Launch settings",
        })
        self.assertEqual(res.status_code, 200, res.content)
        got = APIClient().get(URL).json()["overrides"]
        self.assertEqual(got, {
            "authentication.max_login_attempts": 7,
            "languages.supported": ["fa", "en"],
            "authentication.guest_checkout_enabled": False,
        })

    def test_reset_removes_override_and_is_logged(self):
        self.put({"changes": [{"fieldId": "authentication.max_login_attempts", "value": 7}]})
        res = self.put({"changes": [{"fieldId": "authentication.max_login_attempts", "reset": True}], "reason": "back"})
        self.assertEqual(res.json()["overrides"], {})
        hist = self.client.get(HISTORY, {"field": "authentication.max_login_attempts"}).json()["results"]
        self.assertEqual([h["newValue"] for h in hist], [None, 7])
        self.assertEqual(hist[0]["previousValue"], 7)
        self.assertEqual(hist[0]["reason"], "back")
        self.assertEqual(hist[0]["actorName"], "Root Admin")

    def test_actor_name_without_last_name(self):
        solo = make_user(is_superuser=True, first_name="Root", last_name=None)
        self.put({"changes": [{"fieldId": "authentication.enabled", "value": True}]}, user=solo)
        self.client.force_authenticate(self.root)
        self.assertEqual(self.client.get(HISTORY).json()["results"][0]["actorName"], "Root")

    def test_unchanged_values_are_not_logged(self):
        body = {"changes": [{"fieldId": "authentication.max_login_attempts", "value": 7}]}
        self.put(body)
        self.put(body)
        self.assertEqual(PlatformSettingChange.objects.count(), 1)

    def test_only_superusers_write_or_read_history(self):
        owner, _ = make_tenant()
        body = {"changes": [{"fieldId": "authentication.enabled", "value": False}]}
        self.assertEqual(self.put(body, user=owner).status_code, 403)
        self.assertEqual(self.client.get(HISTORY).status_code, 403)
        anon = APIClient()
        self.assertIn(anon.put(URL, body, format="json").status_code, (401, 403))
        self.assertIn(anon.get(HISTORY).status_code, (401, 403))
        self.assertFalse(PlatformSetting.objects.exists())

    def test_batch_is_all_or_nothing(self):
        res = self.put({"changes": [
            {"fieldId": "authentication.max_login_attempts", "value": 7},
            {"fieldId": "Bad Field!", "value": 1},
        ]})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(PlatformSetting.objects.exists())

    def test_validation(self):
        self.assertEqual(self.put({}).status_code, 400)
        self.assertEqual(self.put({"changes": []}).status_code, 400)
        self.assertEqual(self.put({"changes": [{"fieldId": "a.b"}]}).status_code, 400)
        dup = {"fieldId": "a.b", "value": 1}
        self.assertEqual(self.put({"changes": [dup, dup]}).status_code, 400)
        self.assertEqual(self.put({"changes": [{"fieldId": "a.b", "value": "x" * 70000}]}).status_code, 400)

    def test_does_not_touch_other_platform_settings(self):
        PlatformSetting.objects.create(key="homepage.hero", value={"backgroundImages": []})
        self.put({"changes": [{"fieldId": "authentication.enabled", "value": True}]})
        self.assertEqual(APIClient().get(URL).json()["overrides"], {"authentication.enabled": True})
        self.assertTrue(PlatformSetting.objects.filter(key="homepage.hero").exists())
