"""Regression tests for GET /api/tenants/ — the public tenant-discovery
listing the frontend's discover page (usePublicTenants()) already depends
on. This was accidentally locked down to staff-only during Z.4's tenant-
isolation hardening pass, which is a regression: this endpoint was never
meant to be a per-user membership view (that's GET /api/tenants/me/), it's
a public storefront directory. These tests restore and pin that contract.
"""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Owner, Tenant


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant(**kwargs):
    defaults = {
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": "active",
        "is_active": True,
    }
    defaults.update(kwargs)
    if "owner" not in defaults:
        defaults["owner"] = Owner.objects.create(user=make_user())
    return Tenant.objects.create(**defaults)


class PublicTenantListTests(TestCase):
    def test_anonymous_request_returns_active_public_tenants(self):
        tenant = make_tenant(name="Pizza Place")

        client = APIClient()
        response = client.get("/api/tenants/")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"] if "results" in response.data else response.data
        ids = [item["id"] for item in results]
        self.assertIn(str(tenant.id), ids)

    def test_inactive_tenants_are_excluded(self):
        active_tenant = make_tenant(name="Active Diner", status="active", is_active=True)
        for status_value in ("trial", "suspended", "churned", "archived"):
            make_tenant(name=f"Hidden {status_value}", status=status_value, is_active=True)
        make_tenant(name="Soft disabled", status="active", is_active=False)

        client = APIClient()
        response = client.get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        ids = {item["id"] for item in results}

        self.assertIn(str(active_tenant.id), ids)
        self.assertEqual(len(ids), 1)

    def test_response_shape_matches_discover_contract(self):
        make_tenant(name="Shape Check")

        client = APIClient()
        response = client.get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        self.assertTrue(len(results) >= 1)
        item = results[0]
        self.assertEqual(
            set(item.keys()),
            {
                "id",
                "name",
                "slug",
                "image",
                "business_types",
                "is_active",
                "status",
                "tax_percentage",
                "settings",
                "created_at",
                "updated_at",
            },
        )

    def test_full_tenant_fields_are_returned(self):
        tenant = make_tenant(
            name="Full Fields Check",
            tax_percentage="7.50",
            settings={"theme": {"primaryColor": "#ff0000"}},
            business_types=["cafe", "bar"],
        )

        client = APIClient()
        response = client.get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        item = next(i for i in results if i["id"] == str(tenant.id))

        self.assertEqual(item["name"], "Full Fields Check")
        self.assertEqual(item["slug"], tenant.slug)
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["business_types"], ["cafe", "bar"])
        self.assertEqual(str(item["tax_percentage"]), "7.50")
        # settings is returned exactly as stored -- no defaults merged in,
        # no keys invented (see test_public_settings.py for the dedicated
        # settings-contract test suite).
        self.assertEqual(item["settings"], {"theme": {"primaryColor": "#ff0000"}})
        self.assertIsNotNone(item["created_at"])
        self.assertIsNotNone(item["updated_at"])

    def test_no_ownership_or_membership_fields_leaked(self):
        make_tenant(name="Ownership Check")

        client = APIClient()
        response = client.get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        for item in results:
            self.assertNotIn("owner", item)
            self.assertNotIn("memberships", item)
            self.assertNotIn("roles", item)
            self.assertNotIn("permissions", item)

    def test_type_field_is_not_returned(self):
        """Tenant.type was removed from the backend contract in Z.6.3 —
        the frontend no longer uses it, and it must not appear on any
        tenant API response."""
        make_tenant(name="Type Removed Check")

        client = APIClient()
        response = client.get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        for item in results:
            self.assertNotIn("type", item)
