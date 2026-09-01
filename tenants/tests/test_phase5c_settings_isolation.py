"""Phase 5C: remaining Tenant.settings isolation and projection regressions."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus
from tenants.services.discover_marketplace import build_marketplace_metadata


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


class QuerySetUpdateBypassTests(TestCase):
    def test_queryset_update_bypasses_validation_and_is_not_a_production_write_path(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Bypass Tenant",
            settings={"theme": {"primaryColor": "#123456"}},
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "currency": "EUR",
                "ordering": {"delivery": True},
                "features": {"menu": True},
                "websiteBuilder": {"status": "draft"},
                "legacyExtra": True,
                "marketplace": {"city": "Settings City", "tagline": "Keep"},
            }
        )
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings["currency"], "EUR")
        self.assertTrue(tenant.settings["legacyExtra"])
        self.assertEqual(tenant.settings["marketplace"]["city"], "Settings City")

        tenant.save()
        tenant.refresh_from_db()
        self.assertNotIn("currency", tenant.settings)
        self.assertNotIn("ordering", tenant.settings)
        self.assertNotIn("features", tenant.settings)
        self.assertNotIn("city", tenant.settings.get("marketplace", {}))
        self.assertTrue(tenant.settings["legacyExtra"])
        self.assertEqual(tenant.settings["websiteBuilder"]["status"], "draft")


class SettingsIsolationTests(TestCase):
    def test_branch_fields_are_not_read_from_tenant_settings_by_discover(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Isolation Tenant",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "marketplace": {
                    "tagline": "Listing only",
                    "city": "Settings City",
                    "email": "settings@example.com",
                    "phone_number": "+15550100",
                    "description": "From settings",
                    "coverImage": "https://example.com/settings.jpg",
                    "featured": True,
                }
            }
        )
        tenant.refresh_from_db()
        branch = Branch.objects.create(
            tenant=tenant,
            name="Primary",
            status=BranchStatus.ACTIVE,
            is_active=True,
            marketplace_visible=True,
            is_default=True,
            city="Branch City",
            email="branch@example.com",
            phone="+15559999",
            description="From branch",
        )
        marketplace = build_marketplace_metadata(tenant, [branch])
        self.assertEqual(marketplace["tagline"], "Listing only")
        self.assertTrue(marketplace["featured"])
        self.assertEqual(marketplace["city"], "Branch City")
        self.assertEqual(marketplace["email"], "branch@example.com")
        self.assertEqual(marketplace["phone_number"], "+15559999")
        self.assertEqual(marketplace["description"], "From branch")
        self.assertEqual(marketplace["branchCount"], 1)
        self.assertEqual(marketplace["primaryBranchSlug"], branch.slug)
        self.assertNotIn("branches", marketplace)

    def test_public_retrieve_omits_internal_and_legacy_keys(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Public Filter",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "theme": {"primaryColor": "#123456"},
                "featureFlags": {"menu.enabled": True, "custom.flag": True},
                "addressCapabilities": {"can_deliver": True, "extra.cap": False},
                "notificationMatrix": {"New Order": {"Email": True}},
                "contactEmail": "hello@example.com",
                "legacyExtra": True,
                "marketplace": {"tagline": "Hi", "city": "NYC"},
            }
        )
        tenant.refresh_from_db()
        Branch.objects.create(
            tenant=tenant,
            name="Visible",
            status=BranchStatus.ACTIVE,
            is_active=True,
            marketplace_visible=True,
        )
        retrieve = APIClient().get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(retrieve.status_code, 200, retrieve.data)
        settings = retrieve.data["settings"]
        self.assertEqual(settings["theme"]["primaryColor"], "#123456")
        self.assertTrue(settings["featureFlags"]["custom.flag"])
        self.assertEqual(settings["marketplace"]["tagline"], "Hi")
        self.assertNotIn("city", settings["marketplace"])
        self.assertNotIn("addressCapabilities", settings)
        self.assertNotIn("notificationMatrix", settings)
        self.assertNotIn("legacyExtra", settings)
        self.assertEqual(settings["contactEmail"], "hello@example.com")

    def test_console_me_includes_internal_settings_not_extras(self):
        user = make_user()
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=user),
            name="Console Filter",
            settings={
                "notificationMatrix": {"New Order": {"Email": True}},
                "addressCapabilities": {"can_deliver": True},
                "legacyExtra": True,
            },
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "notificationMatrix": {"New Order": {"Email": True}},
                "addressCapabilities": {"can_deliver": True},
                "legacyExtra": True,
            }
        )
        client = APIClient()
        client.force_authenticate(user=user)
        mine = client.get("/api/tenants/me/")
        item = next(i for i in mine.data["results"] if i["id"] == str(tenant.id))
        self.assertTrue(item["settings"]["notificationMatrix"]["New Order"]["Email"])
        self.assertTrue(item["settings"]["addressCapabilities"]["can_deliver"])
        self.assertNotIn("legacyExtra", item["settings"])

    def test_deprecated_keys_cannot_be_written_through_api(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/tenants/create/",
            data={
                "name": "Deprecated Write",
                "settings": {
                    "currency": "EUR",
                    "websiteBuilder": {},
                    "featureFlags": {"menu.enabled": True},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        ok = client.post(
            "/api/tenants/create/",
            data={
                "name": "Allowed Write",
                "settings": {
                    "featureFlags": {"menu.enabled": True, "custom.dotted": False},
                    "addressCapabilities": {"can_deliver": True, "extra.cap": False},
                },
            },
            format="json",
        )
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertTrue(ok.data["settings"]["featureFlags"]["menu.enabled"])
        self.assertFalse(ok.data["settings"]["featureFlags"]["custom.dotted"])
        self.assertFalse(ok.data["settings"]["addressCapabilities"]["extra.cap"])
        self.assertNotIn("websiteBuilder", ok.data["settings"])
