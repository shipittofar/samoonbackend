"""Tenant.settings persist as caller-owned JSON, except Phase 1/2/4A
duplicated, computed, and unused ``features`` keys which are stripped on write.
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


FULL_SETTINGS = {
    "featureFlags": {
        "menu.enabled": True,
        "reservations.enabled": True,
        "promotions.enabled": True,
        "analytics.enabled": True,
    },
    "theme": {"primaryColor": "#1a1a2e"},
    "marketplace": {
        "tags": ["Live Music", "Happy Hour", "Date Night"],
        "rating": 4.7,
        "reviewCount": 634,
        "featured": True,
        "tagline": "Craft cocktails. Live music. Good company.",
        "priceLevel": 2,
        "gallery": [],
    },
}


class TenantSettingsCreateTests(TestCase):
    def test_create_with_full_settings_payload_round_trips_exactly(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/tenants/create/",
            data={"name": "Full Settings Tenant", "settings": FULL_SETTINGS},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], FULL_SETTINGS)

        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertEqual(tenant.settings, FULL_SETTINGS)

    def test_create_without_settings_stores_empty_object(self):
        """No default values, no fallback settings are invented — an
        omitted `settings` payload stores exactly `{}`, nothing more."""
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/tenants/create/", data={"name": "No Settings Tenant"}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], {})

    def test_create_rejects_non_object_settings(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/tenants/create/",
            data={"name": "Bad Settings Tenant", "settings": "not-an-object"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_does_not_restrict_marketplace_field_shapes(self):
        """A payload with an unconventional/unexpected value in a
        marketplace field (e.g. rating as a string, an extra unknown key)
        must not be rejected or stripped — settings is caller-owned JSON,
        not a strict schema."""
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        unconventional_settings = {
            "marketplace": {"rating": "4.7", "somethingNew": {"nested": True}},
            "customTopLevelKey": ["anything"],
        }

        response = client.post(
            "/api/tenants/create/",
            data={"name": "Unconventional Settings Tenant", "settings": unconventional_settings},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], unconventional_settings)

    def test_create_strips_phase1_duplicated_settings_keys(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        payload = {
            "currency": "EUR",
            "language": "en",
            "timezone": "Europe/Rome",
            "ordering": {
                "dineIn": True,
                "delivery": False,
                "takeaway": True,
                "onlinePayment": False,
            },
            "features": {
                "menu": True,
                "reservations": True,
            },
            "marketplace": {
                "tagline": "Keep this",
                "cuisines": ["Cocktails"],
                "amenities": ["Parking"],
                "openNow": True,
                "branchCount": 99,
                "primaryBranchSlug": "fake-slug",
                "city": "Settings City",
                "email": "settings@example.com",
                "phone_number": "+1 555 0100",
                "description": "From settings",
                "coverImage": "https://example.com/cover.jpg",
                "branches": [{"slug": "ignored"}],
                "rating": 4.7,
            },
            "theme": {"primaryColor": "#1a1a2e"},
            "featureFlags": {"menu.enabled": False},
            "addressCapabilities": {"can_deliver": True},
        }

        response = client.post(
            "/api/tenants/create/",
            data={"name": "Phase1 Strip Tenant", "settings": payload},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        stored = response.data["settings"]
        self.assertNotIn("currency", stored)
        self.assertNotIn("language", stored)
        self.assertNotIn("timezone", stored)
        self.assertNotIn("ordering", stored)
        self.assertNotIn("features", stored)
        self.assertEqual(stored["marketplace"]["tagline"], "Keep this")
        self.assertEqual(stored["marketplace"]["rating"], 4.7)
        self.assertNotIn("cuisines", stored["marketplace"])
        self.assertNotIn("amenities", stored["marketplace"])
        self.assertNotIn("openNow", stored["marketplace"])
        self.assertNotIn("branchCount", stored["marketplace"])
        self.assertNotIn("primaryBranchSlug", stored["marketplace"])
        self.assertNotIn("city", stored["marketplace"])
        self.assertNotIn("email", stored["marketplace"])
        self.assertNotIn("phone_number", stored["marketplace"])
        self.assertNotIn("description", stored["marketplace"])
        self.assertNotIn("coverImage", stored["marketplace"])
        self.assertNotIn("branches", stored["marketplace"])
        self.assertEqual(stored["theme"], {"primaryColor": "#1a1a2e"})
        self.assertEqual(stored["featureFlags"], {"menu.enabled": False})
        self.assertEqual(stored["addressCapabilities"], {"can_deliver": True})

        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertEqual(tenant.settings, stored)


class TenantSettingsUpdateTests(TestCase):
    def _make_owner_and_tenant(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        tenant = make_tenant(name="Update Target", owner=owner)
        return user, tenant

    def test_update_persists_settings_exactly_as_sent(self):
        user, tenant = self._make_owner_and_tenant()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.put(
            f"/api/tenants/{tenant.id}/update/",
            data={"name": tenant.name, "status": "active", "settings": FULL_SETTINGS},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["settings"], FULL_SETTINGS)

        tenant.refresh_from_db()
        self.assertEqual(tenant.settings, FULL_SETTINGS)

    def test_update_with_partial_settings_replaces_stored_value_verbatim(self):
        """No merging over defaults, no filling-in of missing keys: a
        partial settings payload on update simply becomes the new stored
        value, exactly as sent."""
        user, tenant = self._make_owner_and_tenant()
        tenant.settings = FULL_SETTINGS
        tenant.save(update_fields=["settings"])

        partial_settings = {"marketplace": {"rating": 4.9, "tagline": "Alexandria"}}

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.put(
            f"/api/tenants/{tenant.id}/update/",
            data={"name": tenant.name, "status": "active", "settings": partial_settings},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["settings"], partial_settings)
        self.assertNotIn("theme", response.data["settings"])
        self.assertNotIn("featureFlags", response.data["settings"])


class TenantSettingsResponseContractTests(TestCase):
    def test_public_list_returns_settings_unchanged(self):
        make_tenant(name="Public Settings Tenant", settings=FULL_SETTINGS)

        response = APIClient().get("/api/tenants/")

        results = response.data["results"] if "results" in response.data else response.data
        item = next(i for i in results if i["name"] == "Public Settings Tenant")
        self.assertEqual(item["settings"], FULL_SETTINGS)

    def test_retrieve_returns_settings_unchanged(self):
        tenant = make_tenant(name="Retrieve Settings Tenant", settings=FULL_SETTINGS)

        # Current routing: GET /api/tenants/<uuid>/ (slug path does not resolve).
        response = APIClient().get(f"/api/tenants/{tenant.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["settings"], FULL_SETTINGS)

    def test_my_tenants_returns_settings_unchanged(self):
        user = make_user()
        owner = Owner.objects.create(user=user)
        tenant = make_tenant(name="Mine Settings Tenant", settings=FULL_SETTINGS, owner=owner)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/tenants/me/")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"] if "results" in response.data else response.data
        item = next(i for i in results if i["id"] == str(tenant.id))
        self.assertEqual(item["settings"], FULL_SETTINGS)
        self.assertEqual(str(item["owner_id"]), str(user.id))

    def test_empty_settings_returns_empty_object_not_defaults(self):
        """No fallback settings are generated -- a tenant with settings={}
        returns exactly {} everywhere, never an invented default shape."""
        tenant = make_tenant(name="Empty Settings Tenant", settings={})

        response = APIClient().get(f"/api/tenants/{tenant.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["settings"], {})

    def test_no_settings_data_lost_during_serialization(self):
        """Every nested key at every depth of a realistic payload survives
        the full create -> store -> retrieve round trip unchanged."""
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        create_response = client.post(
            "/api/tenants/create/",
            data={"name": "No Data Loss Tenant", "settings": FULL_SETTINGS},
            format="json",
        )
        tenant_id = create_response.data["id"]
        tenant = Tenant.objects.get(id=tenant_id)
        tenant.status = "active"
        tenant.save(update_fields=["status", "settings", "updated_at"])

        retrieve_response = APIClient().get(f"/api/tenants/{tenant_id}/")

        self.assertEqual(retrieve_response.data["settings"], FULL_SETTINGS)
        self.assertEqual(
            retrieve_response.data["settings"]["marketplace"]["tagline"],
            FULL_SETTINGS["marketplace"]["tagline"],
        )
        self.assertNotIn("branches", retrieve_response.data["settings"]["marketplace"])


class TenantFeatureFlagHelperTests(TestCase):
    """tenant.get_feature_flag() is a read-only convenience accessor. It
    never writes back to settings, never invents flags that aren't there,
    and returns exactly the caller-supplied default (not a hardcoded
    value) when a flag is absent."""

    def test_get_feature_flag_reads_from_settings(self):
        tenant = make_tenant(
            name="Flag Tenant", settings={"featureFlags": {"menu.enabled": False}}
        )

        self.assertFalse(tenant.get_feature_flag("menu.enabled"))

    def test_get_feature_flag_returns_caller_supplied_default_when_absent(self):
        tenant = make_tenant(name="Unknown Flag Tenant", settings={})

        self.assertIsNone(tenant.get_feature_flag("nonexistent.flag", default=None))
        self.assertFalse(tenant.get_feature_flag("nonexistent.flag"))
        self.assertTrue(tenant.get_feature_flag("nonexistent.flag", default=True))

    def test_get_feature_flag_on_missing_feature_flags_key(self):
        tenant = make_tenant(name="No Flags Key Tenant", settings={"theme": {}})

        self.assertFalse(tenant.get_feature_flag("menu.enabled"))
