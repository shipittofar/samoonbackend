"""Phase 2: Branch-owned marketplace listing fields vs remaining settings."""
import importlib
import uuid

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus


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
        "status": TenantStatus.ACTIVE,
        "is_active": True,
        "owner": kwargs.pop("owner", None) or Owner.objects.create(user=make_user()),
    }
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def plant_settings(tenant, settings):
    Tenant.objects.filter(pk=tenant.pk).update(settings=settings)
    tenant.refresh_from_db()
    cache.clear()


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "status": BranchStatus.ACTIVE,
        "is_active": True,
        "marketplace_visible": True,
        "city": "Brooklyn",
        "email": "branch@example.com",
        "phone": "+15550001111",
        "description": "Branch description",
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class Phase2WriteSanitizationTests(TestCase):
    def test_create_strips_branch_owned_marketplace_keys_and_keeps_listing_keys(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        payload = {
            "marketplace": {
                "city": "Settings City",
                "email": "settings@example.com",
                "phone_number": "+1 555",
                "description": "Settings about",
                "coverImage": "https://example.com/cover.jpg",
                "branches": [{"slug": "ignored"}],
                "tagline": "Keep tagline",
                "tags": ["Date Night"],
                "featured": True,
                "priceLevel": 3,
                "gallery": ["https://example.com/1.jpg"],
                "rating": 4.8,
                "reviewCount": 12,
            },
            "featureFlags": {"menu.enabled": True},
            "addressCapabilities": {"can_deliver": True},
        }

        response = client.post(
            "/api/tenants/create/",
            data={"name": "Phase2 Marketplace Tenant", "settings": payload},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        stored = response.data["settings"]
        marketplace = stored["marketplace"]
        for key in (
            "city",
            "email",
            "phone_number",
            "description",
            "coverImage",
            "branches",
        ):
            self.assertNotIn(key, marketplace)
        self.assertEqual(marketplace["tagline"], "Keep tagline")
        self.assertEqual(marketplace["tags"], ["Date Night"])
        self.assertTrue(marketplace["featured"])
        self.assertEqual(marketplace["priceLevel"], 3)
        self.assertEqual(marketplace["gallery"], ["https://example.com/1.jpg"])
        self.assertEqual(marketplace["rating"], 4.8)
        self.assertEqual(marketplace["reviewCount"], 12)
        self.assertEqual(stored["featureFlags"], {"menu.enabled": True})
        self.assertEqual(stored["addressCapabilities"], {"can_deliver": True})


class Phase2DiscoverOwnershipTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_stale_marketplace_json_cannot_override_primary_branch_fields(self):
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "marketplace": {
                    "city": "Settings City",
                    "email": "settings@example.com",
                    "phone_number": "+1999",
                    "description": "Settings description",
                    "coverImage": "https://example.com/settings-cover.jpg",
                    "branches": [{"slug": "settings-only", "name": "Fake"}],
                    "tagline": "Keep tagline",
                    "rating": 4.1,
                }
            },
        )
        make_branch(
            tenant,
            slug="real-slug",
            is_default=True,
            city="Brooklyn",
            email="branch@example.com",
            phone="+15550001111",
            description="Branch description",
        )

        response = self.client.get("/api/public/discover/")
        marketplace = response.data["results"][0]["marketplace"]
        branches = response.data["results"][0]["branches"]

        self.assertEqual(marketplace["city"], "Brooklyn")
        self.assertEqual(marketplace["email"], "branch@example.com")
        self.assertEqual(marketplace["phone_number"], "+15550001111")
        self.assertEqual(marketplace["description"], "Branch description")
        self.assertIsNone(marketplace["coverImage"])
        self.assertEqual(marketplace["tagline"], "Keep tagline")
        self.assertEqual(marketplace["rating"], 4.1)
        self.assertNotIn("branches", marketplace)
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["slug"], "real-slug")
        self.assertEqual(branches[0]["location"]["city"], "Brooklyn")

    def test_unresolved_marketplace_fields_still_passthrough(self):
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "marketplace": {
                    "tagline": "Craft cocktails",
                    "tags": ["Live Music"],
                    "featured": True,
                    "priceLevel": 3,
                    "gallery": ["https://example.com/g.jpg"],
                    "rating": 4.7,
                    "reviewCount": 634,
                }
            },
        )
        make_branch(tenant)

        marketplace = self.client.get("/api/public/discover/").data["results"][0][
            "marketplace"
        ]
        self.assertEqual(marketplace["tagline"], "Craft cocktails")
        self.assertEqual(marketplace["tags"], ["Live Music"])
        self.assertTrue(marketplace["featured"])
        self.assertEqual(marketplace["priceLevel"], 3)
        self.assertEqual(marketplace["gallery"], ["https://example.com/g.jpg"])
        self.assertEqual(marketplace["rating"], 4.7)
        self.assertEqual(marketplace["reviewCount"], 634)


class Phase2SettingsMigrationTests(TestCase):
    def test_migration_strips_phase2_keys_only_and_leaves_branch_untouched(self):
        tenant = make_tenant()
        branch = make_branch(
            tenant,
            city="Brooklyn",
            email="branch@example.com",
            phone="+15550001111",
            description="Branch description",
        )
        plant_settings(
            tenant,
            {
                "marketplace": {
                    "city": "Settings City",
                    "email": "settings@example.com",
                    "phone_number": "+1999",
                    "description": "Settings about",
                    "coverImage": "https://example.com/cover.jpg",
                    "branches": [{"slug": "ignored"}],
                    "tagline": "Keep this",
                    "rating": 4.2,
                    "gallery": [],
                },
                "theme": {"primaryColor": "#1a1a2e"},
            },
        )

        module = importlib.import_module(
            "tenants.migrations.0009_strip_phase2_marketplace_settings"
        )
        module.strip_phase2_keys_from_tenant_settings(apps, None)

        tenant.refresh_from_db()
        branch.refresh_from_db()
        self.assertEqual(
            tenant.settings,
            {
                "marketplace": {
                    "tagline": "Keep this",
                    "rating": 4.2,
                    "gallery": [],
                },
                "theme": {"primaryColor": "#1a1a2e"},
            },
        )
        self.assertEqual(branch.city, "Brooklyn")
        self.assertEqual(branch.email, "branch@example.com")
        self.assertEqual(branch.phone, "+15550001111")
        self.assertEqual(branch.description, "Branch description")
        self.assertFalse(branch.cover_image)

        module.strip_phase2_keys_from_tenant_settings(apps, None)
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Keep this")
        self.assertEqual(branch.city, "Brooklyn")
