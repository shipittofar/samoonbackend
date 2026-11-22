from django.test import TestCase
from rest_framework.test import APIClient

from access.tests.helpers import create_canonical_assignment, get_role, make_membership, make_tenant, make_user
from platform_settings.models import PlatformSettingChange, TenantConfigOverride


def url(tenant):
    return f"/api/tenants/{tenant.id}/config/"


BODY = {"changes": [{"fieldId": "payments.default_currency", "value": "IRR"}], "reason": "Toman pricing"}


class TenantConfigApiTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.client = APIClient()

    def put(self, body, user):
        self.client.force_authenticate(user)
        return self.client.put(url(self.tenant), body, format="json")

    def test_owner_saves_and_anyone_reads(self):
        res = self.put(BODY, self.owner)
        self.assertEqual(res.status_code, 200, res.content)
        anon = APIClient()
        anon.credentials(HTTP_AUTHORIZATION="Bearer expired.token.value")
        self.assertEqual(anon.get(url(self.tenant)).json(), {"overrides": {"payments.default_currency": "IRR"}})

    def test_each_business_has_its_own_values(self):
        other_owner, other = make_tenant()
        self.put(BODY, self.owner)
        self.assertEqual(APIClient().get(url(other)).json(), {"overrides": {}})
        # And another business's owner cannot write here.
        self.assertEqual(self.put(BODY, other_owner).status_code, 403)

    def test_staff_without_settings_manage_cannot_write(self):
        waiter = make_user()
        membership = make_membership(user=waiter, tenant=self.tenant)
        create_canonical_assignment(membership=membership, role=get_role("waiter"), all_locations=True)
        self.assertEqual(self.put(BODY, waiter).status_code, 403)
        anon = APIClient()
        self.assertIn(anon.put(url(self.tenant), BODY, format="json").status_code, (401, 403))
        self.assertFalse(TenantConfigOverride.objects.exists())

    def test_platform_superuser_can_write_any_business(self):
        root = make_user(is_superuser=True, is_staff=True)
        self.assertEqual(self.put(BODY, root).status_code, 200)

    def test_reset_and_history_are_per_business(self):
        self.put(BODY, self.owner)
        self.put({"changes": [{"fieldId": "payments.default_currency", "reset": True}]}, self.owner)
        self.assertEqual(APIClient().get(url(self.tenant)).json(), {"overrides": {}})
        hist = self.client.get(url(self.tenant) + "history/").json()["results"]
        self.assertEqual([h["newValue"] for h in hist], [None, "IRR"])
        # Business changes stay out of the platform-wide log.
        root = make_user(is_superuser=True, is_staff=True)
        self.client.force_authenticate(root)
        self.assertEqual(self.client.get("/api/platform/config/history/").json()["results"], [])
        self.assertEqual(PlatformSettingChange.objects.filter(tenant=self.tenant).count(), 2)

    def test_validation_and_unknown_tenant(self):
        self.assertEqual(self.put({"changes": [{"fieldId": "Bad!", "value": 1}]}, self.owner).status_code, 400)
        self.assertEqual(APIClient().get("/api/tenants/00000000-0000-0000-0000-000000000000/config/").status_code, 404)
