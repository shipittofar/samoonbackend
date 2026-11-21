"""Tests for business_types validation and coffee -> cafe migration."""
import uuid

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from tenants.constants.business_type import (
    BUSINESS_TYPE_VALUES,
    normalize_business_types,
    validate_business_types,
)
from tenants.models import Branch, Owner, Tenant
from tenants.services.tenant_activation import enforce_tenant_activation_status

from accounts.models import User


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


class BusinessTypeConstantsTests(TestCase):
    def test_allowed_values_match_contract(self):
        self.assertEqual(
            BUSINESS_TYPE_VALUES,
            frozenset({
                "restaurant",
                "cafe",
                "bar",
                "food_truck",
                "food_court",
                "mobile_cafe",
                "gym",
            }),
        )

    def test_normalize_maps_legacy_coffee_to_cafe(self):
        self.assertEqual(normalize_business_types(["coffee"]), ["cafe"])

    def test_validate_accepts_legacy_coffee_as_cafe(self):
        self.assertEqual(validate_business_types(["coffee"]), ["cafe"])

    def test_validate_accepts_cafe(self):
        self.assertEqual(validate_business_types(["cafe"]), ["cafe"])


class BusinessTypesApiValidationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        Owner.objects.get_or_create(user=self.user)  # approved owners create businesses directly

    def test_create_accepts_legacy_coffee_as_cafe(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={"name": "Legacy Coffee Shop", "business_types": ["coffee"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["business_types"], ["cafe"])

    def test_create_accepts_cafe_value(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={"name": "Modern Cafe", "business_types": ["cafe"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["business_types"], ["cafe"])

    def test_create_accepts_all_allowed_values(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={
                "name": "Multi Type Venue",
                "business_types": sorted(BUSINESS_TYPE_VALUES),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            set(response.data["business_types"]),
            set(BUSINESS_TYPE_VALUES),
        )

    def test_discover_returns_business_types_not_legacy_type(self):
        cache.clear()
        owner, _ = Owner.objects.get_or_create(user=self.user)
        tenant = Tenant.objects.create(
            owner=owner,
            name="Discover Cafe",
            business_types=["cafe"],
        )
        Branch.objects.create(tenant=tenant, name="Main")
        enforce_tenant_activation_status(tenant)

        response = APIClient().get("/api/public/discover/")
        item = next(
            result for result in response.data["results"]
            if result["id"] == str(tenant.id)
        )

        self.assertEqual(item["businessTypes"], ["cafe"])
        self.assertNotIn("type", item)
