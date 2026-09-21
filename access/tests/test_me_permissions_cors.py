"""CORS contract for browser RBAC calls with X-Tenant-Slug."""
from django.test import TestCase


PRODUCTION_ORIGIN = "http://78.157.60.7"


class MePermissionsCorsTests(TestCase):
    def test_preflight_allows_tenant_context_headers(self):
        response = self.client.options(
            "/api/auth/me/permissions/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-tenant-slug,x-tenant-id",
        )

        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("Access-Control-Allow-Headers", "").lower()
        self.assertIn("authorization", allowed)
        self.assertIn("x-tenant-slug", allowed)
        self.assertIn("x-tenant-id", allowed)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")


class UploadInitiateCorsTests(TestCase):
    def test_preflight_allows_idempotency_and_auth_headers(self):
        response = self.client.options(
            "/api/uploads/initiate/",
            HTTP_ORIGIN=PRODUCTION_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=(
                "authorization,content-type,idempotency-key,x-tenant-id"
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_ORIGIN)
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
        allowed = response.headers.get("Access-Control-Allow-Headers", "").lower()
        self.assertIn("authorization", allowed)
        self.assertIn("content-type", allowed)
        self.assertIn("idempotency-key", allowed)
        self.assertIn("x-tenant-id", allowed)
        methods = response.headers.get("Access-Control-Allow-Methods", "").upper()
        self.assertIn("POST", methods)
        self.assertIn("OPTIONS", methods)

    def test_https_frontend_origin_is_allowed(self):
        response = self.client.options(
            "/api/uploads/initiate/",
            HTTP_ORIGIN="https://78.157.60.7",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://78.157.60.7",
        )

    def test_unauthenticated_post_still_has_cors_headers(self):
        response = self.client.post(
            "/api/uploads/initiate/",
            data={"purpose": "tenant_logo"},
            content_type="application/json",
            HTTP_ORIGIN=PRODUCTION_ORIGIN,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_ORIGIN)
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
        self.assertTrue(response.content)

    def test_unknown_origin_does_not_receive_acao(self):
        response = self.client.options(
            "/api/uploads/initiate/",
            HTTP_ORIGIN="https://evil.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertNotEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://evil.example",
        )
        self.assertNotEqual(response.headers.get("Access-Control-Allow-Origin"), "*")
