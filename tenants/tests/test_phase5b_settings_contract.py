"""Phase 5B: Tenant.settings allowlist, public projection, settings patch."""
import uuid

from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import User
from addresses.services.address_capabilities_service import AddressCapabilitiesService
from addresses.services.delivery_zone_service import DeliveryZoneResult
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus
from tenants.settings_cleanup import (
    TenantSettingsContractError,
    project_owner_tenant_settings,
    project_public_tenant_settings,
    strip_deprecated_tenant_settings,
    validate_tenant_settings_contract,
)
from tenants.branding import build_tenant_branding


VALID_SETTINGS = {
    "theme": {
        "primaryColor": "#123456",
        "fontBody": "inter",
    },
    "featureFlags": {
        "menu.enabled": True,
        "custom.flag": False,
    },
    "addressCapabilities": {
        "can_deliver": True,
    },
    "marketplace": {
        "tagline": "Fresh food",
        "featured": True,
        "priceLevel": 2,
        "tags": ["pizza"],
        "gallery": [],
        "rating": 4.5,
        "reviewCount": 12,
    },
    "contactEmail": "hello@example.com",
    "contactPhone": "+15550000000",
    "notificationMatrix": {
        "New Order": {"Email": True, "In-App": True},
    },
}


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


class SettingsContractUnitTests(SimpleTestCase):
    def test_valid_settings_pass(self):
        self.assertEqual(validate_tenant_settings_contract(VALID_SETTINGS), VALID_SETTINGS)

    def test_unknown_top_level_rejected(self):
        with self.assertRaises(TenantSettingsContractError):
            validate_tenant_settings_contract({"websiteBuilder": {}})

    def test_unknown_theme_key_rejected(self):
        with self.assertRaises(TenantSettingsContractError):
            validate_tenant_settings_contract({"theme": {"primaryColor": "#123456", "futureToken": "x"}})

    def test_unknown_marketplace_key_rejected(self):
        with self.assertRaises(TenantSettingsContractError):
            validate_tenant_settings_contract({"marketplace": {"tagline": "x", "somethingNew": True}})

    def test_non_boolean_feature_flag_rejected(self):
        with self.assertRaises(TenantSettingsContractError):
            validate_tenant_settings_contract({"featureFlags": {"menu.enabled": "yes"}})

    def test_custom_flag_boolean_allowed(self):
        cleaned = validate_tenant_settings_contract({"featureFlags": {"custom.flag": True}})
        self.assertTrue(cleaned["featureFlags"]["custom.flag"])

    def test_deprecated_keys_stripped_not_rejected(self):
        cleaned = validate_tenant_settings_contract({
            "currency": "EUR",
            "features": {"menu": True},
            "theme": {"primaryColor": "#123456"},
            "marketplace": {"tagline": "Keep", "city": "NYC", "openNow": True, "heroImage": "https://example.com/h.jpg"},
        })
        self.assertEqual(
            cleaned,
            {"theme": {"primaryColor": "#123456"}, "marketplace": {"tagline": "Keep"}},
        )

    def test_public_projection_omits_internal_keys(self):
        projected = project_public_tenant_settings(VALID_SETTINGS)
        self.assertIn("theme", projected)
        self.assertIn("featureFlags", projected)
        self.assertIn("marketplace", projected)
        self.assertIn("contactEmail", projected)
        self.assertNotIn("addressCapabilities", projected)
        self.assertNotIn("notificationMatrix", projected)

    def test_owner_projection_includes_internal_keys_not_extras(self):
        projected = project_owner_tenant_settings({
            **VALID_SETTINGS,
            "legacyExtra": True,
            "websiteBuilder": {"status": "draft"},
        })
        self.assertEqual(projected["notificationMatrix"], VALID_SETTINGS["notificationMatrix"])
        self.assertTrue(projected["addressCapabilities"]["can_deliver"])
        self.assertNotIn("legacyExtra", projected)
        self.assertNotIn("websiteBuilder", projected)

    def test_save_path_preserves_unknown_stored_keys(self):
        stored = strip_deprecated_tenant_settings({
            "theme": {"primaryColor": "#123456"},
            "legacyExtra": True,
        })
        self.assertTrue(stored["legacyExtra"])


class SettingsContractAPITests(TestCase):
    def test_create_persists_allowed_settings(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/tenants/create/",
            data={"name": "Phase5B Allowed", "settings": VALID_SETTINGS},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], VALID_SETTINGS)

    def test_create_rejects_unknown_and_nested_unknown(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/tenants/create/",
            data={
                "name": "Phase5B Reject",
                "settings": {
                    "theme": {"primaryColor": "#123456", "shadow": "lg"},
                    "websiteBuilder": {"status": "draft"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_patch_settings_merges_and_rejects_unknown(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        tenant = Tenant.objects.create(
            owner=owner,
            name="Patch Tenant",
            settings={"theme": {"primaryColor": "#111111"}},
        )
        client = APIClient()
        client.force_authenticate(user=user)

        ok = client.patch(
            f"/api/tenants/{tenant.id}/settings/",
            data={"featureFlags": {"menu.enabled": True, "custom.flag": True}},
            format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data["settings"]["theme"]["primaryColor"], "#111111")
        self.assertTrue(ok.data["settings"]["featureFlags"]["custom.flag"])

        bad = client.patch(
            f"/api/tenants/{tenant.id}/settings/",
            data={"branchOverrides": {}},
            format="json",
        )
        self.assertEqual(bad.status_code, 400, bad.data)
        tenant.refresh_from_db()
        self.assertNotIn("branchOverrides", tenant.settings)

    def test_patch_preserves_legacy_stored_extras(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        tenant = Tenant.objects.create(
            owner=owner,
            name="Legacy Extra Tenant",
            settings={"theme": {"primaryColor": "#111111"}, "legacyExtra": True},
        )
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"theme": {"primaryColor": "#111111"}, "legacyExtra": True}
        )
        tenant.refresh_from_db()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            f"/api/tenants/{tenant.id}/settings/",
            data={"contactEmail": "keep@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        tenant.refresh_from_db()
        self.assertTrue(tenant.settings["legacyExtra"])
        self.assertEqual(tenant.settings["contactEmail"], "keep@example.com")
        self.assertNotIn("legacyExtra", response.data["settings"])

    def test_public_list_and_retrieve_omit_internal_settings(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Public Settings Filter",
            status=TenantStatus.ACTIVE,
            is_active=True,
            settings=VALID_SETTINGS,
        )
        Branch.objects.create(
            tenant=tenant,
            name="Public Branch",
            status=BranchStatus.ACTIVE,
            is_active=True,
            marketplace_visible=True,
        )
        listed = APIClient().get("/api/tenants/")
        item = next(i for i in listed.data["results"] if i["id"] == str(tenant.id))
        self.assertNotIn("addressCapabilities", item["settings"])
        self.assertNotIn("notificationMatrix", item["settings"])
        self.assertEqual(item["settings"]["theme"]["primaryColor"], "#123456")
        self.assertTrue(item["settings"]["featureFlags"]["menu.enabled"])

        retrieve = APIClient().get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(retrieve.status_code, 200, retrieve.data)
        self.assertNotIn("notificationMatrix", retrieve.data["settings"])
        self.assertIn("featureFlags", retrieve.data["settings"])

        owner_user = tenant.owner.user
        me = APIClient()
        me.force_authenticate(user=owner_user)
        mine = me.get("/api/tenants/me/")
        mine_item = next(i for i in mine.data["results"] if i["id"] == str(tenant.id))
        self.assertEqual(
            mine_item["settings"]["notificationMatrix"]["New Order"]["Email"],
            True,
        )
        self.assertTrue(mine_item["settings"]["addressCapabilities"]["can_deliver"])

    def test_address_capability_overlay_unchanged(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Caps Tenant",
            settings={"addressCapabilities": {"can_deliver": False, "extra.cap": True}},
        )
        branch = Branch.objects.create(
            tenant=tenant,
            name="Main",
            delivery_enabled=True,
            same_day_delivery_enabled=False,
            scheduled_delivery_enabled=True,
            cash_on_delivery_enabled=True,
            contactless_delivery_enabled=True,
        )
        zone = DeliveryZoneResult(
            branch_id=branch.id,
            branch_name=branch.name,
            branch_status=branch.status,
            available=True,
            serviceable=True,
            distance_km=1.0,
            delivery_fee=Decimal("0"),
            estimated_delivery_time=None,
            minimum_order=Decimal("0"),
            currency="USD",
            reason="ok",
        )
        caps = AddressCapabilitiesService().resolve(branch=branch, tenant=tenant, zone=zone)
        self.assertFalse(caps["can_deliver"])
        self.assertTrue(caps["extra.cap"])

    def test_branding_projection_unchanged(self):
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Brand Tenant",
            settings={"theme": {"primaryColor": "#123456", "fontBody": "inter"}},
        )
        branding = build_tenant_branding(tenant)
        self.assertEqual(branding.primaryColor, "#123456")
        self.assertEqual(branding.fontBody, "inter")

    def test_discover_still_exposes_feature_flags(self):
        cache.clear()
        tenant = Tenant.objects.create(
            owner=Owner.objects.create(user=make_user()),
            name="Discover Flags",
            status=TenantStatus.ACTIVE,
            is_active=True,
            settings={"featureFlags": {"menu.enabled": True}},
        )
        Branch.objects.create(
            tenant=tenant,
            name="Visible",
            status=BranchStatus.ACTIVE,
            is_active=True,
            marketplace_visible=True,
            city="NYC",
            address="1 Main",
        )
        response = APIClient().get("/api/public/discover/")
        item = next(i for i in response.data["results"] if i["id"] == str(tenant.id))
        self.assertEqual(item["featureFlags"], {"menu.enabled": True})
        self.assertNotIn("features", item)
