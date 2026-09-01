"""Unit tests for Phase 1 Tenant.settings key stripping."""
from django.test import SimpleTestCase

from tenants.settings_cleanup import strip_phase1_deprecated_tenant_settings


class StripPhase1DeprecatedTenantSettingsTests(SimpleTestCase):
    def test_strips_locale_ordering_reservations_and_marketplace_dupes(self):
        cleaned = strip_phase1_deprecated_tenant_settings({
            "currency": "EUR",
            "timezone": "Europe/Rome",
            "ordering": {"delivery": True},
            "features": {"reservations": True, "menu": True},
            "marketplace": {
                "tagline": "Keep this",
                "cuisines": ["Cocktails"],
                "amenities": ["Parking"],
                "openNow": False,
                "branchCount": 4,
                "primaryBranchSlug": "95aw9pzr",
                "city": "New York",
                "email": "hello@example.com",
                "phone_number": "+1 555",
                "description": "From settings",
                "coverImage": "https://example.com/cover.jpg",
                "branches": [{"slug": "ignored"}],
                "gallery": [],
                "rating": 4.2,
            },
            "theme": {"primaryColor": "#1a1a2e"},
            "featureFlags": {"reservations.enabled": False},
            "addressCapabilities": {"can_deliver": True},
        })

        self.assertEqual(
            cleaned,
            {
                "features": {"menu": True},
                "marketplace": {
                    "tagline": "Keep this",
                    "gallery": [],
                    "rating": 4.2,
                },
                "theme": {"primaryColor": "#1a1a2e"},
                "featureFlags": {"reservations.enabled": False},
                "addressCapabilities": {"can_deliver": True},
            },
        )

    def test_empty_nested_objects_are_removed(self):
        cleaned = strip_phase1_deprecated_tenant_settings({
            "ordering": {"takeaway": True},
            "features": {"reservations": False},
            "marketplace": {"cuisines": ["Bar"]},
        })
        self.assertEqual(cleaned, {})

    def test_idempotent(self):
        once = strip_phase1_deprecated_tenant_settings({"currency": "EUR", "theme": {}})
        twice = strip_phase1_deprecated_tenant_settings(once)
        self.assertEqual(once, twice)
