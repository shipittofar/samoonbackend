"""CORS contract for browser RBAC calls with X-Tenant-Slug."""
from django.test import TestCase


class MePermissionsCorsTests(TestCase):
    def test_preflight_allows_tenant_context_headers(self):
        response = self.client.options(
            "/api/auth/me/permissions/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-tenant-slug,x-tenant-id",
        )

        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("authorization", allowed)
        self.assertIn("x-tenant-slug", allowed)
        self.assertIn("x-tenant-id", allowed)
