"""Tests for GET /api/public/discover/ — public marketplace discovery."""
import uuid
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from core.cache import CacheKeys
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus, WorkingHour
from tenants.selectors import TenantDataAccessLayer

from accounts.models import User

DISCOVER_URL = "/api/public/discover/"
MONDAY_OPEN = datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
MONDAY_CLOSED = datetime(2026, 7, 27, 6, 0, tzinfo=ZoneInfo("UTC"))


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
    user = kwargs.pop("owner_user", None) or make_user()
    owner = Owner.objects.create(user=user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "settings": {},
    }
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def plant_settings(tenant, settings):
    """Bypass Tenant.save sanitizer to leave stale Phase 1 keys in JSON."""
    Tenant.objects.filter(pk=tenant.pk).update(settings=settings)
    tenant.refresh_from_db()
    cache.clear()


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "status": BranchStatus.ACTIVE,
        "is_active": True,
        "marketplace_visible": True,
        "city": "New York",
        "address": "123 Main St",
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def add_working_hours(branch, **day_hours):
    """day_hours: monday=(open, close, is_closed), etc. or pass day index."""
    for day, spec in day_hours.items():
        if isinstance(day, str):
            day = getattr(WorkingHour.Weekday, day.upper())
        open_time, close_time, is_closed = spec
        WorkingHour.objects.create(
            branch=branch,
            day=day,
            open_time=open_time,
            close_time=close_time,
            is_closed=is_closed,
        )


class PublicDiscoverListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_anonymous_request_returns_paginated_response(self):
        tenant = make_tenant(
            name="Pizza Place",
            settings={
                "marketplace": {
                    "description": "Best pizza in town",
                    "rating": 4.8,
                    "branches": [{"slug": "ignored", "name": "Settings Branch"}],
                }
            },
        )
        make_branch(tenant, name="Downtown")

        response = self.client.get(DISCOVER_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

    def test_response_shape_matches_discover_contract(self):
        tenant = make_tenant(
            business_types=["restaurant"],
            settings={
                "featureFlags": {"menu.enabled": True},
                "theme": {"primaryColor": "#e85d04"},
                "marketplace": {
                    "description": "A great spot",
                    "coverImage": "https://example.com/cover.jpg",
                    "city": "New York",
                    "tags": ["Date Night"],
                    "rating": 4.5,
                    "reviewCount": 120,
                    "featured": True,
                    "popular": False,
                    "isNew": True,
                    "priceLevel": 2,
                    "tagline": "Eat well.",
                },
            },
        )
        make_branch(
            tenant,
            name="Main",
            slug="main-branch",
            is_default=True,
            city="Brooklyn",
            email="branch@example.com",
            phone="+15551001001",
            description="Branch about text",
            cuisines=["Italian"],
            amenities=["WiFi"],
        )

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(
            set(item.keys()),
            {
                "id",
                "slug",
                "name",
                "is_active",
                "status",
                "created_at",
                "image",
                "businessTypes",
                "featureFlags",
                "branding",
                "theme",
                "marketplace",
                "branches",
            },
        )
        self.assertEqual(item["status"], "active")
        self.assertIsNotNone(item["created_at"])
        self.assertEqual(item["businessTypes"], ["restaurant"])
        self.assertEqual(item["featureFlags"], {"menu.enabled": True})
        self.assertEqual(item["theme"], {"primaryColor": "#e85d04"})
        self.assertEqual(item["branding"]["primaryColor"], "#e85d04")
        self.assertIn("image", item)
        self.assertEqual(item["marketplace"]["description"], "Branch about text")
        self.assertEqual(item["marketplace"]["city"], "Brooklyn")
        self.assertEqual(item["marketplace"]["email"], "branch@example.com")
        self.assertEqual(item["marketplace"]["phone_number"], "+15551001001")
        self.assertIsNone(item["marketplace"]["coverImage"])
        self.assertEqual(item["marketplace"]["rating"], 4.5)
        self.assertEqual(item["marketplace"]["branchCount"], 1)
        self.assertEqual(item["marketplace"]["primaryBranchSlug"], "main-branch")
        self.assertNotIn("branches", item["marketplace"])
        self.assertNotIn("description", item)
        self.assertNotIn("cuisines", item["marketplace"])
        self.assertNotIn("amenities", item["marketplace"])

        branch = item["branches"][0]
        self.assertEqual(
            set(branch.keys()),
            {
                "id",
                "slug",
                "name",
                "image",
                "cuisines",
                "amenities",
                "openNow",
                "todayHours",
                "location",
            },
        )
        self.assertEqual(branch["cuisines"], ["Italian"])
        self.assertEqual(branch["amenities"], ["WiFi"])
        self.assertEqual(set(branch["location"].keys()), {"address", "city", "country"})

    def test_cuisines_and_amenities_come_from_branch_not_tenant_settings(self):
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "marketplace": {
                    "cuisines": ["From Settings"],
                    "amenities": ["Settings Amenity"],
                    "tagline": "Keep this",
                }
            },
        )
        make_branch(
            tenant,
            name="Main",
            cuisines=["Italian"],
            amenities=["WiFi"],
        )

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(item["marketplace"]["tagline"], "Keep this")
        self.assertNotIn("cuisines", item["marketplace"])
        self.assertNotIn("amenities", item["marketplace"])
        self.assertEqual(item["branches"][0]["cuisines"], ["Italian"])
        self.assertEqual(item["branches"][0]["amenities"], ["WiFi"])

    def test_inactive_tenants_are_excluded(self):
        active_tenant = make_tenant(name="Active Diner")
        make_tenant(name="Closed Diner", status=TenantStatus.CLOSED)
        make_tenant(name="Inactive Diner", status=TenantStatus.INACTIVE)
        make_tenant(
            name="Hidden Active",
            status=TenantStatus.ACTIVE,
            is_active=False,
        )
        make_branch(active_tenant)

        response = self.client.get(DISCOVER_URL)

        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(active_tenant.id)})

    def test_stale_discover_cache_excludes_deactivated_tenant(self):
        tenant = make_tenant(name="Cached Then Hidden")
        make_branch(tenant)
        TenantDataAccessLayer.get_discover_tenants()

        tenant.is_active = False
        tenant.save(update_fields=["is_active"])

        response = self.client.get(DISCOVER_URL)
        ids = {item["id"] for item in response.data["results"]}
        self.assertNotIn(str(tenant.id), ids)

    def test_public_branches_are_included(self):
        tenant = make_tenant()
        branch = make_branch(
            tenant,
            name="Visible Branch",
            city="Brooklyn",
            address="456 Oak Ave",
        )

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(len(item["branches"]), 1)
        self.assertEqual(item["branches"][0]["id"], str(branch.id))
        self.assertEqual(item["branches"][0]["name"], "Visible Branch")
        self.assertEqual(item["branches"][0]["location"]["city"], "Brooklyn")
        self.assertEqual(item["branches"][0]["location"]["address"], "456 Oak Ave")

    def test_branch_filtering_excludes_non_public_branches(self):
        tenant = make_tenant()
        visible = make_branch(tenant, name="Visible")
        make_branch(
            tenant,
            name="Inactive",
            is_active=False,
            status=BranchStatus.INACTIVE,
        )
        make_branch(
            tenant,
            name="Hidden",
            marketplace_visible=False,
        )

        response = self.client.get(DISCOVER_URL)
        branch_ids = {branch["id"] for branch in response.data["results"][0]["branches"]}

        self.assertEqual(branch_ids, {str(visible.id)})

    def test_tenant_with_no_public_branches_returns_empty_branch_list(self):
        tenant = make_tenant(name="No Branches Yet")
        make_tenant(name="Other Active")

        response = self.client.get(DISCOVER_URL)
        item = next(
            result for result in response.data["results"]
            if result["id"] == str(tenant.id)
        )

        self.assertEqual(item["branches"], [])

    def test_pagination_limits_results(self):
        for index in range(25):
            make_tenant(name=f"Tenant {index:02d}")

        response = self.client.get(DISCOVER_URL, {"page_size": 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 25)
        self.assertEqual(len(response.data["results"]), 10)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_branches_do_not_come_from_settings_marketplace(self):
        tenant = make_tenant(
            settings={
                "marketplace": {
                    "description": "Configured in settings",
                    "branches": [
                        {
                            "slug": "settings-only",
                            "name": "Settings Branch",
                            "city": "Settings City",
                        }
                    ],
                }
            },
        )
        make_branch(tenant, name="Real Branch", slug="real-branch")

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(len(item["branches"]), 1)
        self.assertEqual(item["branches"][0]["slug"], "real-branch")
        self.assertNotEqual(item["branches"][0]["name"], "Settings Branch")

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "discover-cache-tests",
            }
        }
    )
    def test_discover_list_is_cached_and_refreshed_on_invalidation(self):
        tenant = make_tenant(name="Cached Tenant")
        make_branch(tenant, name="First Branch")

        first_response = self.client.get(DISCOVER_URL)
        self.assertEqual(len(first_response.data["results"][0]["branches"]), 1)
        self.assertIsNotNone(cache.get(CacheKeys.DISCOVER_LIST))

        make_branch(tenant, name="Second Branch")
        stale_response = self.client.get(DISCOVER_URL)
        self.assertEqual(len(stale_response.data["results"][0]["branches"]), 1)

        TenantDataAccessLayer._refresh_discover_list_cache()
        refreshed_response = self.client.get(DISCOVER_URL)
        self.assertEqual(len(refreshed_response.data["results"][0]["branches"]), 2)

    def test_query_count_uses_single_prefetch_for_branches(self):
        tenant_one = make_tenant(name="Tenant One")
        tenant_two = make_tenant(name="Tenant Two")
        make_branch(tenant_one, name="Branch A")
        make_branch(tenant_one, name="Branch B")
        make_branch(tenant_two, name="Branch C")

        cache.clear()

        # 1 tenants + 1 batched branches + 1 batched working_hours (no N+1).
        with self.assertNumQueries(3):
            list(TenantDataAccessLayer.get_discover_tenants())

        response = self.client.get(DISCOVER_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_primary_branch_slug_prefers_default_branch(self):
        tenant = make_tenant()
        plant_settings(tenant, {"marketplace": {"primaryBranchSlug": "stale-slug"}})
        make_branch(tenant, name="Alpha", slug="alpha", is_default=False)
        make_branch(tenant, name="Central", slug="central", is_default=True)

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(item["marketplace"]["primaryBranchSlug"], "central")

    def test_primary_branch_slug_falls_back_to_first_public_branch(self):
        tenant = make_tenant()
        first = make_branch(tenant, name="Alpha", slug="alpha", is_default=False)
        make_branch(tenant, name="Beta", slug="beta", is_default=False)

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(item["marketplace"]["primaryBranchSlug"], first.slug)

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_open_now_returns_true_during_open_window(self, mock_now):
        mock_now.return_value = MONDAY_OPEN
        tenant = make_tenant()
        branch = make_branch(tenant, time_zone="UTC")
        add_working_hours(branch, monday=(time(9, 0), time(22, 0), False))

        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertTrue(branch_data["openNow"])
        self.assertEqual(branch_data["todayHours"], "09:00-22:00")

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_open_now_returns_false_when_closed(self, mock_now):
        mock_now.return_value = MONDAY_CLOSED
        tenant = make_tenant()
        branch = make_branch(tenant, time_zone="UTC")
        add_working_hours(branch, monday=(time(9, 0), time(22, 0), False))

        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertFalse(branch_data["openNow"])

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_today_hours_returns_current_day_schedule(self, mock_now):
        mock_now.return_value = MONDAY_OPEN
        tenant = make_tenant()
        branch = make_branch(tenant, time_zone="UTC")
        add_working_hours(branch, monday=(time(10, 30), time(18, 45), False))

        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertEqual(branch_data["todayHours"], "10:30-18:45")

    def test_branch_count_matches_returned_branches(self):
        tenant = make_tenant()
        plant_settings(
            tenant, {"marketplace": {"branchCount": 99, "rating": 4.2}}
        )
        make_branch(tenant, name="Branch One")
        make_branch(tenant, name="Branch Two")
        make_branch(
            tenant,
            name="Hidden Branch",
            marketplace_visible=False,
        )

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertEqual(len(item["branches"]), 2)
        self.assertEqual(item["marketplace"]["branchCount"], 2)
        self.assertEqual(item["marketplace"]["rating"], 4.2)

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_marketplace_open_now_is_computed_not_stored(self, mock_now):
        mock_now.return_value = MONDAY_CLOSED
        tenant = make_tenant()
        plant_settings(tenant, {"marketplace": {"openNow": True}})
        branch = make_branch(tenant, time_zone="UTC")
        add_working_hours(branch, monday=(time(9, 0), time(22, 0), False))

        response = self.client.get(DISCOVER_URL)
        item = response.data["results"][0]

        self.assertFalse(item["marketplace"]["openNow"])

    def test_branch_without_working_hour_does_not_fail(self):
        tenant = make_tenant()
        make_branch(tenant)

        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertIsNone(branch_data["todayHours"])
        self.assertFalse(branch_data["openNow"])

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_timezone_correctness_uses_branch_timezone(self, mock_now):
        # 06:00 UTC is 09:30 in Asia/Tehran on Monday.
        mock_now.return_value = datetime(2026, 7, 27, 6, 0, tzinfo=ZoneInfo("UTC"))
        tenant = make_tenant()
        branch = make_branch(tenant, time_zone="Asia/Tehran")
        add_working_hours(branch, monday=(time(9, 0), time(22, 0), False))

        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertTrue(branch_data["openNow"])

        mock_now.return_value = datetime(2026, 7, 27, 2, 0, tzinfo=ZoneInfo("UTC"))
        cache.clear()
        response = self.client.get(DISCOVER_URL)
        branch_data = response.data["results"][0]["branches"][0]

        self.assertFalse(branch_data["openNow"])
