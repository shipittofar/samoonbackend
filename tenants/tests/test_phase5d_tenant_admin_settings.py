"""Phase 5D: Django Admin Tenant.settings follows the locked contract."""
import json
import uuid

from django.test import TestCase

from accounts.models import User
from tenants.admin.tenant import TenantAdminForm
from tenants.models import Owner, Tenant
from tenants.settings_cleanup import (
    project_owner_tenant_settings,
    replace_canonical_tenant_settings,
)


CANONICAL = {
    "theme": {"primaryColor": "#123456"},
    "featureFlags": {"menu.enabled": True},
    "addressCapabilities": {"can_deliver": True},
    "marketplace": {"tagline": "Test restaurant"},
    "contactEmail": "hello@example.com",
    "contactPhone": "+15550001111",
    "notificationMatrix": {"New Order": {"Email": True}},
}


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
        "is_staff": True,
        "is_superuser": True,
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


def admin_form(tenant, settings_payload):
    return TenantAdminForm(
        data={
            "owner": str(tenant.owner_id),
            "name": tenant.name,
            "status": tenant.status,
            "is_active": "on",
            "tax_percentage": str(tenant.tax_percentage),
            "service_charge_percentage": str(tenant.service_charge_percentage),
            "business_types": json.dumps(tenant.business_types or []),
            "settings": json.dumps(settings_payload),
        },
        instance=tenant,
    )


class ReplaceCanonicalSettingsTests(TestCase):
    def test_preserves_unknown_extras(self):
        merged = replace_canonical_tenant_settings(
            {"theme": {"primaryColor": "#111111"}, "legacyExtra": True},
            {"theme": {"primaryColor": "#123456"}},
        )
        self.assertEqual(merged["theme"]["primaryColor"], "#123456")
        self.assertTrue(merged["legacyExtra"])


class TenantAdminFormSettingsTests(TestCase):
    def test_canonical_settings_can_be_saved(self):
        tenant = make_tenant()
        form = admin_form(tenant, {
            "theme": {"primaryColor": "#123456"},
            "featureFlags": {"menu.enabled": True},
            "marketplace": {"tagline": "Test restaurant"},
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings["theme"]["primaryColor"], "#123456")
        self.assertTrue(tenant.settings["featureFlags"]["menu.enabled"])
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Test restaurant")

    def test_features_is_stripped_and_not_reintroduced(self):
        tenant = make_tenant()
        form = admin_form(tenant, {"features": {"orders": True}})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertNotIn("features", tenant.settings)

    def test_domain_owned_keys_are_not_stored(self):
        tenant = make_tenant()
        form = admin_form(tenant, {
            "currency": "EUR",
            "language": "en",
            "timezone": "Europe/Rome",
            "ordering": {"delivery": True},
            "marketplace": {
                "tagline": "Keep",
                "city": "Settings City",
                "phone_number": "+15550100",
                "description": "From settings",
            },
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertNotIn("currency", tenant.settings)
        self.assertNotIn("language", tenant.settings)
        self.assertNotIn("timezone", tenant.settings)
        self.assertNotIn("ordering", tenant.settings)
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Keep")
        self.assertNotIn("city", tenant.settings["marketplace"])
        self.assertNotIn("phone_number", tenant.settings["marketplace"])
        self.assertNotIn("description", tenant.settings["marketplace"])

    def test_closed_objects_reject_unknown_keys(self):
        tenant = make_tenant()
        for payload in (
            {"theme": {"unknownKey": True}},
            {"marketplace": {"unknownKey": True}},
            {"marketplace": {"socialLinks": {"unknownKey": "https://x.example"}}},
        ):
            form = admin_form(tenant, payload)
            self.assertFalse(form.is_valid(), payload)
            self.assertIn("settings", form.errors)

    def test_open_maps_accept_arbitrary_boolean_keys(self):
        tenant = make_tenant()
        form = admin_form(tenant, {
            "featureFlags": {"custom.flag": True},
            "addressCapabilities": {"customCapability": True},
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertTrue(tenant.settings["featureFlags"]["custom.flag"])
        self.assertTrue(tenant.settings["addressCapabilities"]["customCapability"])

    def test_existing_canonical_settings_survive_admin_save(self):
        tenant = make_tenant(settings=CANONICAL)
        form = admin_form(tenant, CANONICAL)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings["theme"], CANONICAL["theme"])
        self.assertEqual(tenant.settings["featureFlags"], CANONICAL["featureFlags"])
        self.assertEqual(tenant.settings["addressCapabilities"], CANONICAL["addressCapabilities"])
        self.assertEqual(tenant.settings["marketplace"], CANONICAL["marketplace"])
        self.assertEqual(tenant.settings["contactEmail"], CANONICAL["contactEmail"])
        self.assertEqual(tenant.settings["contactPhone"], CANONICAL["contactPhone"])
        self.assertEqual(tenant.settings["notificationMatrix"], CANONICAL["notificationMatrix"])

    def test_legacy_extras_are_not_shown_and_not_deleted(self):
        tenant = make_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                **CANONICAL,
                "legacyExtra": True,
                "websiteBuilder": {"status": "draft"},
            }
        )
        tenant.refresh_from_db()

        unbound = TenantAdminForm(instance=tenant)
        shown = unbound.initial["settings"]
        self.assertNotIn("legacyExtra", shown)
        self.assertNotIn("websiteBuilder", shown)
        self.assertEqual(shown["theme"]["primaryColor"], "#123456")
        self.assertEqual(project_owner_tenant_settings(tenant.settings)["theme"], CANONICAL["theme"])

        form = admin_form(tenant, CANONICAL)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        tenant.refresh_from_db()
        self.assertTrue(tenant.settings["legacyExtra"])
        self.assertEqual(tenant.settings["websiteBuilder"]["status"], "draft")
        self.assertEqual(tenant.settings["theme"]["primaryColor"], "#123456")
        self.assertTrue(tenant.settings["featureFlags"]["menu.enabled"])

    def test_pasting_unknown_top_level_key_is_rejected(self):
        tenant = make_tenant()
        form = admin_form(tenant, {"websiteBuilder": {"status": "draft"}})
        self.assertFalse(form.is_valid())
        self.assertIn("settings", form.errors)
