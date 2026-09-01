"""Phase 1: Branch/domain fields remain the source of truth over Tenant.settings."""
import importlib
import uuid
from datetime import datetime, time
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from core.exceptions.orders import (
    OrderTypeNotEnabledException,
    PaymentMethodNotEnabledException,
)
from menu.models import MenuCategory, MenuItem
from orders.models import OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from tenants.api.serializers.response.tenant_response import BranchResponseSerializer
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus, WorkingHour


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
        "currency": "USD",
        "language": "en",
        "time_zone": "UTC",
        "pickup_enabled": True,
        "delivery_enabled": False,
        "table_ordering_enabled": False,
        "online_payment_enabled": False,
        "reservations_enabled": False,
        "ordering_enabled": True,
        "cash_payment_enabled": True,
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class TenantSaveStripsPhase1KeysTests(TestCase):
    def test_save_does_not_copy_deprecated_keys_onto_branch(self):
        tenant = make_tenant()
        branch = make_branch(
            tenant,
            currency="USD",
            language="en",
            time_zone="UTC",
            delivery_enabled=False,
            pickup_enabled=False,
            table_ordering_enabled=False,
            online_payment_enabled=False,
            reservations_enabled=False,
            cuisines=["Italian"],
            amenities=["WiFi"],
        )
        tenant.settings = {
            "currency": "EUR",
            "language": "it",
            "timezone": "Europe/Rome",
            "ordering": {
                "dineIn": True,
                "delivery": True,
                "takeaway": True,
                "onlinePayment": True,
            },
            "features": {"reservations": True},
            "marketplace": {
                "cuisines": ["Cocktails"],
                "amenities": ["Parking"],
            },
        }
        tenant.save()
        tenant.refresh_from_db()
        branch.refresh_from_db()

        self.assertNotIn("currency", tenant.settings)
        self.assertNotIn("ordering", tenant.settings)
        self.assertNotIn("features", tenant.settings)
        self.assertNotIn("marketplace", tenant.settings)
        self.assertEqual(branch.currency, "USD")
        self.assertEqual(branch.language, "en")
        self.assertEqual(branch.time_zone, "UTC")
        self.assertFalse(branch.delivery_enabled)
        self.assertFalse(branch.pickup_enabled)
        self.assertFalse(branch.table_ordering_enabled)
        self.assertFalse(branch.online_payment_enabled)
        self.assertFalse(branch.reservations_enabled)
        self.assertEqual(branch.cuisines, ["Italian"])
        self.assertEqual(branch.amenities, ["WiFi"])


class LocaleOwnershipTests(TestCase):
    def test_branch_locale_not_overridden_by_tenant_settings(self):
        tenant = make_tenant()
        branch = make_branch(
            tenant, currency="IRR", language="fa", time_zone="Asia/Tehran"
        )
        plant_settings(
            tenant,
            {
                "currency": "EUR",
                "language": "it",
                "timezone": "Europe/Rome",
            },
        )
        branch.refresh_from_db()
        data = BranchResponseSerializer(branch).data

        self.assertEqual(data["currency"], "IRR")
        self.assertEqual(data["language"], "fa")
        self.assertEqual(data["timeZone"], "Asia/Tehran")
        self.assertEqual(branch.currency, "IRR")
        self.assertEqual(branch.language, "fa")
        self.assertEqual(branch.time_zone, "Asia/Tehran")


class OrderingOwnershipTests(TestCase):
    def test_settings_ordering_does_not_enable_disabled_branch_checkout(self):
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "ordering": {
                    "dineIn": True,
                    "delivery": True,
                    "takeaway": True,
                    "onlinePayment": True,
                }
            },
        )
        branch = make_branch(
            tenant,
            delivery_enabled=False,
            pickup_enabled=True,
            table_ordering_enabled=False,
            online_payment_enabled=False,
        )
        category = MenuCategory.objects.create(branch=branch, name="Mains")
        item = MenuItem.objects.create(
            branch=branch, category=category, name="Burger", price=Decimal("10.00")
        )
        customer = make_user()
        bll = OrdersBusinessLogicLayer()
        item_payload = [{"menu_item_id": item.id, "quantity": 1}]

        with self.assertRaises(OrderTypeNotEnabledException):
            bll.create_order(
                customer=customer,
                validated_data={
                    "branch_id": branch.id,
                    "order_type": OrderType.DELIVERY,
                    "payment_method": PaymentMethod.CASH,
                    "items": item_payload,
                    "delivery_address": {"street": "1 Main", "city": "LA"},
                },
            )

        with self.assertRaises(OrderTypeNotEnabledException):
            bll.create_order(
                customer=customer,
                validated_data={
                    "branch_id": branch.id,
                    "order_type": OrderType.DINE_IN,
                    "payment_method": PaymentMethod.CASH,
                    "table_number": 1,
                    "items": item_payload,
                },
            )

        with self.assertRaises(PaymentMethodNotEnabledException):
            bll.create_order(
                customer=customer,
                validated_data={
                    "branch_id": branch.id,
                    "order_type": OrderType.PICKUP,
                    "payment_method": PaymentMethod.ONLINE,
                    "items": item_payload,
                },
            )

        order = bll.create_order(
            customer=customer,
            validated_data={
                "branch_id": branch.id,
                "order_type": OrderType.PICKUP,
                "payment_method": PaymentMethod.CASH,
                "items": item_payload,
            },
        )
        self.assertEqual(order.order_type, OrderType.PICKUP)


class ReservationsOwnershipTests(TestCase):
    def test_branch_reservations_enabled_is_authoritative(self):
        tenant = make_tenant()
        plant_settings(tenant, {"features": {"reservations": True}})
        branch = make_branch(tenant, reservations_enabled=False)
        data = BranchResponseSerializer(branch).data

        self.assertFalse(data["reservationsEnabled"])
        self.assertFalse(branch.reservations_enabled)


class Phase1SettingsMigrationTests(TestCase):
    def test_migration_strips_only_phase1_keys_and_leaves_branch_untouched(self):
        tenant = make_tenant()
        branch = make_branch(
            tenant,
            currency="USD",
            cuisines=["Italian"],
            amenities=["WiFi"],
        )
        plant_settings(
            tenant,
            {
                "currency": "EUR",
                "timezone": "Europe/Rome",
                "ordering": {"delivery": True},
                "features": {"menu": True, "reservations": True},
                "marketplace": {
                    "tagline": "Keep this",
                    "cuisines": ["Cocktails"],
                    "openNow": True,
                    "branchCount": 99,
                    "primaryBranchSlug": "fake",
                },
                "theme": {"primaryColor": "#1a1a2e"},
            },
        )

        module = importlib.import_module(
            "tenants.migrations.0008_strip_phase1_tenant_settings"
        )
        module.strip_phase1_keys_from_tenant_settings(apps, None)

        tenant.refresh_from_db()
        branch.refresh_from_db()
        self.assertEqual(
            tenant.settings,
            {
                "features": {"menu": True},
                "marketplace": {"tagline": "Keep this"},
                "theme": {"primaryColor": "#1a1a2e"},
            },
        )
        self.assertEqual(branch.currency, "USD")
        self.assertEqual(branch.cuisines, ["Italian"])
        self.assertEqual(branch.amenities, ["WiFi"])

        module.strip_phase1_keys_from_tenant_settings(apps, None)
        tenant.refresh_from_db()
        self.assertEqual(tenant.settings["marketplace"]["tagline"], "Keep this")


class DiscoverComputedOwnershipTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @patch("tenants.services.branch_availability.django_timezone.now")
    def test_stale_marketplace_computed_keys_cannot_override_discover(self, mock_now):
        mock_now.return_value = datetime(2026, 7, 27, 6, 0, tzinfo=ZoneInfo("UTC"))
        tenant = make_tenant()
        plant_settings(
            tenant,
            {
                "marketplace": {
                    "openNow": True,
                    "branchCount": 999,
                    "primaryBranchSlug": "fake-slug",
                    "cuisines": ["From Settings"],
                    "amenities": ["From Settings"],
                }
            },
        )
        branch = make_branch(
            tenant,
            name="Real",
            slug="real-slug",
            is_default=True,
            time_zone="UTC",
            cuisines=["Italian"],
            amenities=["WiFi"],
        )
        WorkingHour.objects.create(
            branch=branch,
            day=WorkingHour.Weekday.MONDAY,
            open_time=time(9, 0),
            close_time=time(22, 0),
            is_closed=False,
        )

        response = self.client.get("/api/public/discover/")
        item = response.data["results"][0]
        marketplace = item["marketplace"]

        self.assertFalse(marketplace["openNow"])
        self.assertEqual(marketplace["branchCount"], 1)
        self.assertEqual(marketplace["primaryBranchSlug"], "real-slug")
        self.assertNotIn("cuisines", marketplace)
        self.assertNotIn("amenities", marketplace)
        self.assertEqual(item["branches"][0]["cuisines"], ["Italian"])
        self.assertEqual(item["branches"][0]["amenities"], ["WiFi"])
