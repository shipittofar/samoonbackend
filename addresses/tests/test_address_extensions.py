"""Tests for address serviceability, branch resolution, capabilities, and suggestions."""

import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from addresses.domain.address_type import AddressType
from addresses.domain.geocoder import GeocoderProvider, GeocoderService, SuggestionResult
from addresses.services.address_domain_service import AddressDomainService
from tenants.models import Branch, Owner, Tenant, TenantStatus


def make_user(**kwargs):
    user = User(
        id=uuid.uuid4(),
        phone_number=kwargs.get("phone_number", f"+1555{uuid.uuid4().int % 10**7:07d}"),
        country_code=kwargs.get("country_code", "+1"),
        email=kwargs.get("email", f"{uuid.uuid4().hex}@example.com"),
        first_name=kwargs.get("first_name", "Jane"),
        last_name=kwargs.get("last_name", "Doe"),
    )
    user.set_password("testpass123")
    user.save()
    return user


def auth_client(user):
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def make_branch(*, delivery_enabled=True, delivery_radius=50, **overrides):
    owner = Owner.objects.create(user=make_user())
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
        status=TenantStatus.ACTIVE,
        is_active=True,
    )
    defaults = {
        "name": "Main",
        "latitude": Decimal("34.050000"),
        "longitude": Decimal("-118.250000"),
        "currency": "USD",
        "delivery_enabled": delivery_enabled,
        "delivery_radius_km": delivery_radius,
        "minimum_order_amount": Decimal("15.00"),
        "cash_on_delivery_enabled": True,
        "contactless_delivery_enabled": True,
        "scheduled_delivery_enabled": True,
        "same_day_delivery_enabled": False,
        "pickup_enabled": True,
        "table_ordering_enabled": False,
        "reservations_enabled": False,
        "ordering_enabled": True,
        "marketplace_visible": True,
    }
    defaults.update(overrides)
    return Branch.objects.create(tenant=tenant, **defaults)


def valid_address_payload(**overrides):
    payload = {
        "address_type": AddressType.HOME,
        "country": "US",
        "province": "CA",
        "city": "Los Angeles",
        "street": "123 Main St",
        "postal_code": "90001",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "is_default": True,
    }
    payload.update(overrides)
    return payload


class StubGeocoder(GeocoderProvider):
    name = "stub"

    def geocode(self, *, street: str, city: str, country: str, postal_code: str = ""):
        return None

    def suggest(self, *, query: str, country: str = "", city: str = "", language: str = ""):
        if not query:
            return []
        return [
            SuggestionResult(
                formatted_address=f"{query}, Los Angeles, US",
                latitude=34.05,
                longitude=-118.25,
                provider="stub",
                confidence=0.9,
            )
        ]


class ServiceabilityAPITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.branch = make_branch()
        self.user.active_branch = self.branch
        self.user.save(update_fields=["active_branch_id"])
        self.client = auth_client(self.user)
        created = self.client.post(
            "/api/users/addresses/", valid_address_payload(), format="json"
        )
        self.address_id = created.data["id"]

    def test_get_serviceability_for_saved_address(self):
        response = self.client.get(
            f"/api/users/addresses/{self.address_id}/serviceability/",
            {"branch_id": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["serviceable"])
        self.assertEqual(response.data["assigned_branch"]["id"], str(self.branch.id))
        self.assertEqual(response.data["minimum_order"], "15.00")
        self.assertEqual(response.data["currency"], "USD")

    def test_get_serviceability_requires_ownership(self):
        other = make_user()
        other_client = auth_client(other)
        response = other_client.get(
            f"/api/users/addresses/{self.address_id}/serviceability/",
            {"branch_id": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, 404)

    def test_post_check_serviceability_with_address_id(self):
        response = self.client.post(
            "/api/users/addresses/check-serviceability/",
            {
                "branch_id": str(self.branch.id),
                "address_id": self.address_id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["serviceable"])

    def test_post_check_serviceability_with_inline_address(self):
        response = self.client.post(
            "/api/users/addresses/check-serviceability/",
            {
                "branch_id": str(self.branch.id),
                "delivery_address": {
                    "street": "500 Test Blvd",
                    "city": "Los Angeles",
                    "zip": "90001",
                    "lat": 34.0522,
                    "lng": -118.2437,
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("delivery_fee", response.data)

    def test_not_serviceable_returns_reason(self):
        response = self.client.post(
            "/api/users/addresses/check-serviceability/",
            {
                "branch_id": str(make_branch(delivery_radius=1).id),
                "delivery_address": {
                    "street": "Far",
                    "city": "San Francisco",
                    "zip": "94102",
                    "lat": 37.7749,
                    "lng": -122.4194,
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["serviceable"])
        self.assertIsNotNone(response.data["reason"])


class BranchResolutionAPITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.branch = make_branch(delivery_radius=25)
        self.client = auth_client(self.user)
        created = self.client.post(
            "/api/users/addresses/", valid_address_payload(), format="json"
        )
        self.address_id = created.data["id"]

    def test_get_branch_for_address(self):
        response = self.client.get(
            f"/api/users/addresses/{self.address_id}/branch/",
            {"branch_id": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data["id"]), str(self.branch.id))
        self.assertEqual(response.data["name"], "Main")
        self.assertEqual(response.data["delivery_radius"], 25.0)


class CapabilitiesAPITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.branch = make_branch()
        self.client = auth_client(self.user)
        created = self.client.post(
            "/api/users/addresses/", valid_address_payload(), format="json"
        )
        self.address_id = created.data["id"]

    def test_capabilities_in_list_when_branch_id_provided(self):
        response = self.client.get(
            "/api/users/addresses/",
            {"branch_id": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["results"][0]["capabilities"]["can_deliver"])

    def test_capabilities_in_detail_when_branch_id_provided(self):
        response = self.client.get(
            f"/api/users/addresses/{self.address_id}/",
            {"branch_id": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, 200)
        caps = response.data["capabilities"]
        self.assertTrue(caps["can_deliver"])
        self.assertTrue(caps["supports_cash_on_delivery"])
        self.assertFalse(caps["supports_same_day"])


class SuggestionsAPITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.domain = AddressDomainService(geocoder=GeocoderService(StubGeocoder()))

    def test_suggestions_endpoint_empty_with_noop(self):
        response = self.client.get("/api/users/addresses/suggestions/", {"query": "Main"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["suggestions"], [])

    def test_domain_suggest_with_stub_provider(self):
        suggestions = self.domain.suggest_addresses(query="123 Main", country="US")
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["provider"], "stub")

    def test_suggestions_empty_query(self):
        response = self.client.get("/api/users/addresses/suggestions/", {"query": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["suggestions"], [])

    def test_anonymous_suggestions_returns_401(self):
        response = APIClient().get("/api/users/addresses/suggestions/", {"query": "x"})
        self.assertEqual(response.status_code, 401)
