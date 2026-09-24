"""QR redirects and encoded resolver URLs follow configured public origins."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from access.tests.helpers import make_branch, make_tenant
from tenants.api.serializers.response.qr import serialize_qr_management
from tenants.models import QrCode
from tenants.models.qr_code import QrEntityType
from tenants.services.public_url import absolute_public_url

PUBLIC_ORIGIN = "http://78.157.60.7"


@override_settings(PUBLIC_SITE_URL=PUBLIC_ORIGIN, PUBLIC_API_URL=PUBLIC_ORIGIN)
class QrPublicOriginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="Origin Branch")

    def _active(self, entity_type, entity_id):
        return QrCode.objects.get(
            entity_type=entity_type, entity_id=entity_id, is_active=True
        )

    def test_absolute_public_url_uses_site_origin_without_dev_port(self):
        url = absolute_public_url(f"/{self.tenant.slug}/{self.branch.slug}/menu")
        self.assertEqual(
            url,
            f"{PUBLIC_ORIGIN}/{self.tenant.slug}/{self.branch.slug}/menu",
        )
        self.assertNotIn(":3000", url)
        self.assertNotIn("localhost", url)

    def test_tenant_qr_location(self):
        qr = self._active(QrEntityType.TENANT, self.tenant.id)
        response = self.client.get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{PUBLIC_ORIGIN}/{self.tenant.slug}")
        self.assertNotIn(":3000", response["Location"])

    def test_branch_qr_location(self):
        qr = self._active(QrEntityType.BRANCH, self.branch.id)
        response = self.client.get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{PUBLIC_ORIGIN}/{self.tenant.slug}/{self.branch.slug}",
        )

    def test_menu_qr_location(self):
        qr = self._active(QrEntityType.MENU, self.branch.id)
        response = self.client.get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{PUBLIC_ORIGIN}/{self.tenant.slug}/{self.branch.slug}/menu",
        )
        self.assertNotIn(":3000", response["Location"])

    def test_reservation_qr_location(self):
        qr = self._active(QrEntityType.RESERVATION, self.branch.id)
        response = self.client.get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{PUBLIC_ORIGIN}/{self.tenant.slug}/{self.branch.slug}/reservation",
        )

    def test_management_url_uses_public_api_origin(self):
        qr = self._active(QrEntityType.MENU, self.branch.id)
        payload = serialize_qr_management(qr, request=None)
        self.assertEqual(payload["url"], f"{PUBLIC_ORIGIN}/qr/{qr.code}")
        self.assertNotIn(":3000", payload["url"])
        self.assertNotIn("localhost", payload["url"])

    def test_slug_change_keeps_configured_origin(self):
        qr = self._active(QrEntityType.MENU, self.branch.id)
        self.branch.slug = "renamed-branch"
        self.branch.save(update_fields=["slug", "updated_at"])
        response = self.client.get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{PUBLIC_ORIGIN}/{self.tenant.slug}/renamed-branch/menu",
        )
