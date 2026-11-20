"""Branch service area, pin verification, and the discover payload that carries them.

Contract: frontend Phase L1 (service area), L2 (pin verification, server-stamped),
L3 (discover: branch coordinates + public menu text for item search).
A business (tenant) has no location of its own — only branches do.
"""
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from menu.models import MenuCategory, MenuItem
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus
from tenants.service_area import (
    MAX_MENU_NAMES_PER_BRANCH,
    ServiceAreaError,
    resolve_location_verified_at,
    validate_service_area,
)

CIRCLE = {"mode": "on_site", "shape": {"type": "circle", "radiusKm": 6}}
PATCH_URL = "/api/branches/{branch_id}/"
DISCOVER_URL = "/api/public/discover/"
T0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=dt_timezone.utc)


# ── pure rules ───────────────────────────────────────────────────────────────

class ValidateServiceAreaTests(SimpleTestCase):
    def test_none_clears(self):
        self.assertIsNone(validate_service_area(None))

    def test_circle_is_normalised_and_unknown_keys_dropped(self):
        result = validate_service_area({**CIRCLE, "junk": 1, "shape": {**CIRCLE["shape"], "x": 2}})
        self.assertEqual(result, {"mode": "on_site", "shape": {"type": "circle", "radiusKm": 6.0}})

    def test_polygon(self):
        points = [{"lat": 35.7, "lng": 51.4}, {"lat": 35.8, "lng": 51.4}, {"lat": 35.8, "lng": 51.5}]
        result = validate_service_area({"mode": "delivery", "shape": {"type": "polygon", "points": points}})
        self.assertEqual(result["shape"]["points"], points)

    def test_zones_must_ascend_and_fit_inside_the_radius(self):
        zones = [{"upToKm": 3, "fee": 0, "etaMinutes": 30}, {"upToKm": 6, "fee": 2.5, "etaMinutes": 45}]
        self.assertEqual(validate_service_area({**CIRCLE, "zones": zones})["zones"], [
            {"upToKm": 3.0, "fee": 0.0, "etaMinutes": 30.0},
            {"upToKm": 6.0, "fee": 2.5, "etaMinutes": 45.0},
        ])
        for bad in ([{"upToKm": 6}, {"upToKm": 3}], [{"upToKm": 7}], [{"upToKm": 3, "fee": -1}]):
            with self.assertRaises(ServiceAreaError):
                validate_service_area({**CIRCLE, "zones": bad})

    def test_rejects_bad_input(self):
        circle = lambda r: {"mode": "delivery", "shape": {"type": "circle", "radiusKm": r}}  # noqa: E731
        bad = [
            "circle",
            {"mode": "teleport", "shape": CIRCLE["shape"]},
            {"mode": "delivery"},
            circle(0), circle(-1), circle(501), circle("6"), circle(True), circle(float("nan")),
            {"mode": "delivery", "shape": {"type": "square"}},
            {"mode": "delivery", "shape": {"type": "polygon", "points": [{"lat": 1, "lng": 1}] * 2}},
            {"mode": "delivery", "shape": {"type": "polygon", "points": [{"lat": 99, "lng": 1}] * 3}},
            {"mode": "delivery", "shape": {"type": "polygon", "points": [{"lat": 0, "lng": 0}] * 3}},
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ServiceAreaError):
                validate_service_area(value)


class ResolveLocationVerifiedAtTests(SimpleTestCase):
    def resolve(self, **kwargs):
        defaults = dict(stored=None, provided=False, incoming=None, coordinates_changed=False, now=T0)
        defaults.update(kwargs)
        return resolve_location_verified_at(**defaults)

    def test_a_confirmation_is_stamped_with_server_time_not_the_client_clock(self):
        client_time = T0 - timedelta(days=400)
        self.assertEqual(self.resolve(provided=True, incoming=client_time), T0)

    def test_null_clears(self):
        self.assertIsNone(self.resolve(stored=T0, provided=True, incoming=None))

    def test_echoing_the_stored_value_keeps_it(self):
        # microseconds are lost when a client round-trips the timestamp
        echoed = T0.replace(microsecond=0)
        stored = T0.replace(microsecond=123456)
        self.assertEqual(self.resolve(stored=stored, provided=True, incoming=echoed, now=T0 + timedelta(hours=1)), stored)

    def test_echoing_the_stored_value_while_the_pin_moves_resets(self):
        self.assertIsNone(self.resolve(stored=T0, provided=True, incoming=T0, coordinates_changed=True))

    def test_moving_the_pin_without_confirmation_resets(self):
        self.assertIsNone(self.resolve(stored=T0, coordinates_changed=True))

    def test_untouched_stays(self):
        self.assertEqual(self.resolve(stored=T0), T0)

    def test_confirming_after_moving_in_the_same_request_is_a_fresh_confirmation(self):
        later = T0 + timedelta(hours=2)
        self.assertEqual(
            self.resolve(stored=T0, provided=True, incoming=later - timedelta(minutes=1), coordinates_changed=True, now=later),
            later,
        )


# ── API ──────────────────────────────────────────────────────────────────────

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


def make_tenant(user=None, **kwargs):
    owner = Owner.objects.create(user=user or make_user())
    defaults = {"owner": owner, "name": f"Tenant {uuid.uuid4().hex[:6]}", "status": TenantStatus.ACTIVE, "settings": {}}
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "status": BranchStatus.ACTIVE,
        "is_active": True,
        "marketplace_visible": True,
        "city": "Tehran",
        "address": "Vanak Sq",
        "latitude": Decimal("35.757500"),
        "longitude": Decimal("51.409700"),
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class ConsoleBranchServiceAreaAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = make_user()
        self.tenant = make_tenant(self.user)
        self.branch = make_branch(self.tenant)
        self.client.force_authenticate(user=self.user)
        self.url = PATCH_URL.format(branch_id=self.branch.id)

    def patch(self, payload):
        return self.client.patch(self.url, payload, format="json")

    def test_new_branch_has_no_custom_area_and_is_unverified(self):
        data = self.patch({"name": "Renamed"}).json()
        self.assertIsNone(data["serviceArea"])
        self.assertIsNone(data["locationVerifiedAt"])

    def test_service_area_is_saved_returned_and_cleared_by_null(self):
        response = self.patch({"serviceArea": CIRCLE})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["serviceArea"], {"mode": "on_site", "shape": {"type": "circle", "radiusKm": 6.0}})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.service_area["shape"]["radiusKm"], 6.0)

        cleared = self.patch({"serviceArea": None})
        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        self.assertIsNone(cleared.json()["serviceArea"])

    def test_omitting_service_area_leaves_it_unchanged(self):
        self.patch({"serviceArea": CIRCLE})
        self.patch({"name": "Other name"})
        self.branch.refresh_from_db()
        self.assertIsNotNone(self.branch.service_area)

    def test_invalid_service_area_is_a_400_with_a_message(self):
        response = self.patch({"serviceArea": {"mode": "delivery", "shape": {"type": "circle", "radiusKm": 9999}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("serviceArea", response.json())
        self.branch.refresh_from_db()
        self.assertIsNone(self.branch.service_area)

    def test_service_area_as_json_string_in_multipart(self):
        import json

        response = self.client.patch(self.url, {"serviceArea": json.dumps(CIRCLE)}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["serviceArea"]["mode"], "on_site")

    def test_confirming_the_pin_stores_server_time_not_the_client_clock(self):
        before = timezone.now()
        client_clock = "2020-01-01T00:00:00Z"
        data = self.patch({"locationVerifiedAt": client_clock}).json()
        self.assertIsNotNone(data["locationVerifiedAt"])
        self.branch.refresh_from_db()
        self.assertGreaterEqual(self.branch.location_verified_at, before)

    def test_resending_the_stored_confirmation_does_not_bump_it(self):
        self.patch({"locationVerifiedAt": "2020-01-01T00:00:00Z"})
        self.branch.refresh_from_db()
        stored = self.branch.location_verified_at
        echoed = stored.isoformat()
        self.patch({"name": "Edit", "locationVerifiedAt": echoed})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.location_verified_at, stored)

    def test_moving_the_pin_resets_the_confirmation(self):
        self.patch({"locationVerifiedAt": "2020-01-01T00:00:00Z"})
        response = self.patch({"location": {"latitude": "35.800000", "longitude": "51.450000"}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["locationVerifiedAt"])

    def test_saving_the_same_coordinates_keeps_the_confirmation(self):
        self.patch({"locationVerifiedAt": "2020-01-01T00:00:00Z"})
        self.branch.refresh_from_db()
        stored = self.branch.location_verified_at
        self.patch({"location": {"latitude": "35.7575", "longitude": "51.4097"}})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.location_verified_at, stored)

    def test_null_clears_the_confirmation(self):
        self.patch({"locationVerifiedAt": "2020-01-01T00:00:00Z"})
        self.assertIsNone(self.patch({"locationVerifiedAt": None}).json()["locationVerifiedAt"])


class DiscoverLocationPayloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.tenant = make_tenant(name="Pizza Co", business_types=["restaurant"])
        self.branch = make_branch(
            self.tenant,
            name="Vanak",
            service_area={"mode": "delivery", "shape": {"type": "circle", "radiusKm": 5.0}},
            location_verified_at=T0,
        )
        pizza = MenuCategory.objects.create(branch=self.branch, name="Pizza")
        grill = MenuCategory.objects.create(branch=self.branch, name="Grill")
        MenuItem.objects.create(branch=self.branch, category=pizza, name="Margherita", price=Decimal("9.00"), is_popular=True)
        MenuItem.objects.create(branch=self.branch, category=pizza, name="Pepperoni", price=Decimal("11.00"))
        # same name in another category → listed once
        MenuItem.objects.create(branch=self.branch, category=grill, name="Margherita", price=Decimal("9.00"))
        # not searchable: unpublished, not orderable
        MenuItem.objects.create(branch=self.branch, category=grill, name="Hidden", price=Decimal("1.00"), is_active=False)
        MenuItem.objects.create(branch=self.branch, category=grill, name="Sold out", price=Decimal("1.00"), available=False)

    def branch_payload(self):
        response = self.client.get(DISCOVER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = next(r for r in response.json()["results"] if r["name"] == "Pizza Co")
        return item, item["branches"][0]

    def test_branch_pin_service_area_and_verification_are_public(self):
        _, branch = self.branch_payload()
        self.assertEqual(branch["location"]["latitude"], "35.757500")
        self.assertEqual(branch["location"]["longitude"], "51.409700")
        self.assertEqual(branch["serviceArea"]["mode"], "delivery")
        self.assertIsNotNone(branch["locationVerifiedAt"])

    def test_menu_text_lists_published_orderable_items_once_popular_first(self):
        _, branch = self.branch_payload()
        self.assertEqual(branch["menuItemNames"], ["Margherita", "Pepperoni"])
        self.assertEqual(sorted(branch["menuCategoryNames"]), ["Grill", "Pizza"])

    def test_menu_names_are_capped(self):
        category = MenuCategory.objects.create(branch=self.branch, name="Bulk")
        MenuItem.objects.bulk_create([
            MenuItem(branch=self.branch, category=category, name=f"Item {i:04d}", price=Decimal("1.00"), slug=f"bulk-{i}")
            for i in range(MAX_MENU_NAMES_PER_BRANCH + 25)
        ])
        cache.clear()
        _, branch = self.branch_payload()
        self.assertEqual(len(branch["menuItemNames"]), MAX_MENU_NAMES_PER_BRANCH)

    def test_a_branch_with_no_menu_has_empty_lists(self):
        empty_tenant = make_tenant(name="No Menu Co")
        make_branch(empty_tenant, name="Empty")
        results = self.client.get(DISCOVER_URL).json()["results"]
        branch = next(r for r in results if r["name"] == "No Menu Co")["branches"][0]
        self.assertEqual(branch["menuItemNames"], [])
        self.assertEqual(branch["menuCategoryNames"], [])

    def test_a_business_has_no_location_of_its_own(self):
        item, _ = self.branch_payload()
        for key in ("latitude", "longitude", "location", "serviceArea"):
            self.assertNotIn(key, item)
        self.assertNotIn("latitude", item["marketplace"])
        self.assertNotIn("longitude", item["marketplace"])
