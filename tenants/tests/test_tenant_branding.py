"""Tests for shared tenant branding projection and validation."""
import importlib
import uuid

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.branding import (
    TenantBranding,
    build_legacy_discover_theme,
    build_tenant_branding,
    validate_tenant_branding,
)
from tenants.models import Branch, Owner, Tenant
from tenants.services.tenant_activation import enforce_tenant_activation_status


class BrandingModuleArchitectureTests(SimpleTestCase):
    def test_curated_font_ids_constant_does_not_exist(self):
        branding = importlib.import_module("tenants.branding")
        self.assertFalse(hasattr(branding, "CURATED_FONT_IDS"))

    def test_supported_locales_constant_does_not_exist(self):
        branding = importlib.import_module("tenants.branding")
        self.assertFalse(hasattr(branding, "SUPPORTED_LOCALES"))


class BuildTenantBrandingTests(SimpleTestCase):
    def _tenant(self, settings=None):
        return type("TenantStub", (), {"settings": settings or {}})()

    def test_missing_settings(self):
        tenant = type("TenantStub", (), {})()
        branding = build_tenant_branding(tenant)
        self.assertEqual(branding, TenantBranding())

    def test_missing_theme(self):
        branding = build_tenant_branding(self._tenant({"featureFlags": {}}))
        self.assertEqual(branding, TenantBranding())

    def test_missing_individual_branding_fields(self):
        branding = build_tenant_branding(
            self._tenant({"theme": {"primaryColor": "#112233"}})
        )
        self.assertEqual(branding.primaryColor, "#112233")
        self.assertIsNone(branding.accentHoverColor)
        self.assertIsNone(branding.fontBody)
        self.assertEqual(branding.fontsByLocale, {})

    def test_complete_branding(self):
        branding = build_tenant_branding(
            self._tenant(
                {
                    "theme": {
                        "primaryColor": "#112233",
                        "accentHoverColor": "#aabbcc",
                        "fontBody": "inter",
                        "fontsByLocale": {"en": "inter", "fa": "vazir"},
                    }
                }
            )
        )
        self.assertEqual(branding.primaryColor, "#112233")
        self.assertEqual(branding.accentHoverColor, "#aabbcc")
        self.assertEqual(branding.fontBody, "inter")
        self.assertEqual(branding.fontsByLocale, {"en": "inter", "fa": "vazir"})

    def test_unknown_theme_keys_ignored_in_projection(self):
        branding = build_tenant_branding(
            self._tenant(
                {"theme": {"primaryColor": "#112233", "futureToken": "keep-in-db"}}
            )
        )
        self.assertEqual(branding.primaryColor, "#112233")
        self.assertFalse(hasattr(branding, "futureToken"))

    def test_legacy_discover_theme_from_branding(self):
        branding = TenantBranding(primaryColor="#112233", accentHoverColor="#aabbcc")
        self.assertEqual(
            build_legacy_discover_theme(branding),
            {"primaryColor": "#112233"},
        )
        self.assertNotIn("logo", build_legacy_discover_theme(branding))
        self.assertNotIn("accentHoverColor", build_legacy_discover_theme(branding))


class ValidateTenantBrandingTests(SimpleTestCase):
    def test_valid_colors(self):
        validate_tenant_branding(
            {"primaryColor": "#112233", "accentHoverColor": "#AABBCC"}
        )

    def test_invalid_colors(self):
        with self.assertRaises(ValueError):
            validate_tenant_branding({"primaryColor": "red"})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"accentHoverColor": "#abc"})

    def test_valid_font_body(self):
        validate_tenant_branding({"fontBody": "inter"})

    def test_invalid_font_body(self):
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontBody": ""})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontBody": "Inter"})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontBody": "a" * 65})

    def test_css_injection_attempts_rejected(self):
        for bad in [
            "font;evil",
            "font{evil}",
            'font"evil',
            "font'evil",
            "url(evil)",
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_tenant_branding({"fontBody": bad})

    def test_valid_fonts_by_locale(self):
        validate_tenant_branding(
            {"fontsByLocale": {"en": "inter", "fa-ir": "vazir", "xx": "noto-sans"}}
        )

    def test_invalid_fonts_by_locale_shape(self):
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontsByLocale": "bad"})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontsByLocale": {"": "inter"}})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontsByLocale": {"en": ""}})
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontsByLocale": {"x" * 11: "inter"}})

    def test_too_many_locale_entries_rejected(self):
        fonts = {f"l{i}": "inter" for i in range(11)}
        with self.assertRaises(ValueError):
            validate_tenant_branding({"fontsByLocale": fonts})

    def test_theme_logo_url_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_tenant_branding({"logoUrl": "data:image/png;base64,abc"})
        self.assertIn("image field", str(ctx.exception))

    def test_theme_logo_key_rejected(self):
        with self.assertRaises(ValueError):
            validate_tenant_branding({"logo": "https://example.com/logo.png"})

    def test_unknown_theme_keys_allowed(self):
        validate_tenant_branding(
            {"primaryColor": "#112233", "futureToken": "some-value"}
        )


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


class TenantBrandingCrudTests(TestCase):
    def test_valid_theme_accepted(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        settings = {
            "theme": {
                "primaryColor": "#112233",
                "accentHoverColor": "#aabbcc",
                "fontBody": "inter",
                "fontsByLocale": {"en": "inter"},
                "futureToken": "allowed",
            }
        }
        response = client.post(
            "/api/tenants/create/",
            data={"name": "Branded Tenant", "settings": settings},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], settings)

    def test_invalid_branding_rejected(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/tenants/create/",
            data={
                "name": "Bad Branding Tenant",
                "settings": {"theme": {"primaryColor": "not-a-color"}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_logo_url_rejected(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/tenants/create/",
            data={
                "name": "Logo URL Tenant",
                "settings": {"theme": {"logoUrl": "https://example.com/logo.png"}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("image field", str(response.data))

    def test_opaque_non_branding_settings_remain_supported(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        settings = {"marketplace": {"rating": "4.7"}, "customKey": True}
        response = client.post(
            "/api/tenants/create/",
            data={"name": "Opaque Settings Tenant", "settings": settings},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["settings"], settings)


class DiscoverBrandingApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_discover_exposes_branding_image_and_legacy_theme(self):
        owner = Owner.objects.create(user=make_user())
        tenant = Tenant.objects.create(
            owner=owner,
            name="Discover Branding",
            settings={
                "theme": {
                    "primaryColor": "#e85d04",
                    "accentHoverColor": "#ffba08",
                    "fontBody": "inter",
                    "fontsByLocale": {"en": "inter", "fa": "vazir"},
                }
            },
        )
        Branch.objects.create(tenant=tenant, name="Main")
        enforce_tenant_activation_status(tenant)
        response = self.client.get("/api/public/discover/")
        item = next(i for i in response.data["results"] if i["id"] == str(tenant.id))

        self.assertEqual(
            item["branding"],
            {
                "primaryColor": "#e85d04",
                "accentHoverColor": "#ffba08",
                "fontBody": "inter",
                "fontsByLocale": {"en": "inter", "fa": "vazir"},
            },
        )
        self.assertEqual(item["theme"], {"primaryColor": "#e85d04"})
        self.assertIn("image", item)
        self.assertNotIn("logo", item["theme"])
        self.assertNotIn("logo", item.get("branding", {}))
