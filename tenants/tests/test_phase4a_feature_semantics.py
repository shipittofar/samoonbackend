"""Phase 4A: unused settings.features is stripped; featureFlags remain.

Does not change RBAC, Discover shape, Owner.plan, or Branch capabilities.
"""
import importlib
import uuid

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.services.rbac_bll import rbac_bll
from access.tests.helpers import make_tenant as make_access_tenant
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


class Phase4AFeaturesStripTests(TestCase):
    def test_create_does_not_persist_features_and_keeps_feature_flags(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        Owner.objects.get_or_create(user=user)  # approved owners create businesses directly

        response = client.post(
            "/api/tenants/create/",
            data={
                "name": "Phase4A Features Tenant",
                "settings": {
                    "features": {
                        "menu": True,
                        "orders": True,
                        "loyalty": True,
                        "reports": True,
                        "inventory": True,
                    },
                    "featureFlags": {
                        "menu.enabled": True,
                        "analytics.enabled": False,
                        "promotions.enabled": True,
                        "reservations.enabled": False,
                    },
                    "theme": {"primaryColor": "#1a1a2e"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        stored = response.data["settings"]
        self.assertNotIn("features", stored)
        self.assertEqual(
            stored["featureFlags"],
            {
                "menu.enabled": True,
                "analytics.enabled": False,
                "promotions.enabled": True,
                "reservations.enabled": False,
            },
        )
        self.assertEqual(stored["theme"], {"primaryColor": "#1a1a2e"})

        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertEqual(tenant.settings, stored)

        me = client.get("/api/tenants/me/")
        self.assertEqual(me.status_code, 200, me.data)
        results = me.data["results"] if "results" in me.data else me.data
        item = next(i for i in results if i["id"] == str(tenant.id))
        self.assertNotIn("features", item["settings"])
        self.assertEqual(item["settings"]["featureFlags"], stored["featureFlags"])

    def test_migration_strips_features_is_idempotent_and_keeps_unrelated_keys(self):
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "features": {"menu": True, "orders": False},
                "featureFlags": {"menu.enabled": True},
                "marketplace": {"tagline": "Keep this"},
            },
        )

        module = importlib.import_module(
            "tenants.migrations.0010_strip_phase4a_features_settings"
        )
        module.strip_features_from_tenant_settings(apps, None)
        tenant.refresh_from_db()
        self.assertNotIn("features", tenant.settings)
        self.assertEqual(tenant.settings["featureFlags"], {"menu.enabled": True})
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Keep this")

        module.strip_features_from_tenant_settings(apps, None)
        tenant.refresh_from_db()
        self.assertEqual(
            tenant.settings,
            {
                "featureFlags": {"menu.enabled": True},
                "marketplace": {"tagline": "Keep this"},
            },
        )


class Phase4ADiscoverFeatureFlagsKeptTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_discover_still_exposes_feature_flags(self):
        tenant = make_tenant()
        Branch.objects.create(
            tenant=tenant,
            name="Public Branch",
            status=BranchStatus.ACTIVE,
            is_active=True,
            marketplace_visible=True,
            city="New York",
            address="123 Main St",
        )
        plant_settings(
            tenant,
            {"featureFlags": {"menu.enabled": True, "reservations.enabled": False}},
        )
        response = APIClient().get("/api/public/discover/")
        self.assertEqual(response.status_code, 200, response.data)
        item = next(i for i in response.data["results"] if i["id"] == str(tenant.id))
        self.assertIn("featureFlags", item)
        self.assertEqual(
            item["featureFlags"],
            {"menu.enabled": True, "reservations.enabled": False},
        )
        self.assertNotIn("features", item)


class Phase4AIsolationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_feature_flags_false_does_not_remove_owner_or_change_plan_permissions(self):
        owner_user, tenant = make_access_tenant()
        tenant.owner.plan = "free"
        tenant.owner.max_tenants = 1
        tenant.owner.save(update_fields=["plan", "max_tenants"])
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "featureFlags": {
                    "menu.enabled": False,
                    "analytics.enabled": False,
                    "promotions.enabled": False,
                    "reservations.enabled": False,
                }
            }
        )
        cache.clear()
        effective = set(rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant))
        self.assertEqual(effective, ROLE_PERMISSIONS["owner"])

    def test_auth_me_does_not_expose_tenant_feature_flags_or_features(self):
        owner_user, tenant = make_access_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"featureFlags": {"menu.enabled": True}, "features": {"menu": True}}
        )
        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("featureFlags", response.data)
        self.assertNotIn("features", response.data)
        ownership = response.data["ownership"]
        self.assertTrue(ownership)
        self.assertIn("plan", ownership[0])
        self.assertIn("maxTenants", ownership[0])
        me_text = str(response.data)
        self.assertNotIn("menu.enabled", me_text)
