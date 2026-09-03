"""Tenant detail lookup contract.

Current routing resolves GET /api/tenants/<uuid:tenant_id>/. A bare slug
path does not match the UUID converter (Resolver404). /auth/me/ still
exposes tenantSlug for client-side routing against public list/discover.
"""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Owner, Tenant


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
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


class TenantDetailLookupTests(TestCase):
    def test_retrieve_by_uuid_returns_tenant(self):
        tenant = make_tenant(name="Cocktail Bar")

        response = APIClient().get(f"/api/tenants/{tenant.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(tenant.id))
        self.assertEqual(response.data["name"], "Cocktail Bar")
        self.assertEqual(response.data["slug"], tenant.slug)

    def test_invalid_uuid_returns_404(self):
        response = APIClient().get(
            f"/api/tenants/{uuid.uuid4()}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_slug_path_does_not_resolve_under_uuid_route(self):
        """Slug-shaped paths are not accepted by <uuid:tenant_id>."""
        tenant = make_tenant(name="Slug Should Not Match UUID Route")

        response = APIClient().get(f"/api/tenants/{tenant.slug}/")

        self.assertEqual(response.status_code, 404)

    def test_retrieve_by_uuid_works_without_authentication(self):
        tenant = make_tenant(name="Public Detail Tenant")

        response = APIClient().get(f"/api/tenants/{tenant.id}/")

        self.assertEqual(response.status_code, 200)

    def test_response_shape_matches_tenant_retrieve_serializer(self):
        tenant = make_tenant(name="Shape Unchanged Tenant")

        response = APIClient().get(f"/api/tenants/{tenant.id}/")

        self.assertEqual(
            set(response.data.keys()),
            {
                "id",
                "owner_id",
                "name",
                "slug",
                "description",
                "tax_percentage",
                "serviceChargePercentage",
                "image",
                "discoverAvatar",
                "discoverCover",
                "heroImage",
                "business_types",
                "is_active",
                "status",
                "settings",
                "created_at",
                "updated_at",
            },
        )


class AuthMeTenantIdAndSlugTests(TestCase):
    """/auth/me/ must keep returning both tenantId (internal relations)
    and tenantSlug (routing/resolution) -- no breaking removal."""

    def test_me_returns_both_tenant_id_and_slug(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        tenant = make_tenant(name="Both Fields Tenant", owner=owner)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        membership_payload = response.json()["memberships"][0]
        self.assertEqual(membership_payload["tenantId"], str(tenant.id))
        self.assertEqual(membership_payload["tenantName"], tenant.name)
        self.assertEqual(membership_payload["tenantSlug"], tenant.slug)

        # tenantId from /auth/me/ must resolve the UUID detail endpoint.
        detail_response = APIClient().get(
            f"/api/tenants/{membership_payload['tenantId']}/"
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["id"], membership_payload["tenantId"])
        self.assertEqual(detail_response.data["slug"], membership_payload["tenantSlug"])
