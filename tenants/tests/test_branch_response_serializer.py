"""Unit tests for BranchResponseSerializer checkout contract."""

import uuid
from decimal import Decimal

from django.test import TestCase

from tenants.api.serializers.response.tenant_response import BranchResponseSerializer
from tenants.models import Branch, BranchOrderType, BranchPaymentMethod, Owner, Tenant
from accounts.models import User


def make_branch(**overrides):
    user = User.objects.create(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}")
    defaults = {
        "tenant": tenant,
        "name": "Main Branch",
        "ordering_enabled": True,
        "delivery_enabled": True,
        "pickup_enabled": True,
        "table_ordering_enabled": False,
        "default_order_type": BranchOrderType.DELIVERY,
        "delivery_radius_km": 10,
        "minimum_order_amount": Decimal("20.00"),
        "same_day_delivery_enabled": False,
        "scheduled_delivery_enabled": True,
        "contactless_delivery_enabled": False,
        "cash_payment_enabled": True,
        "cash_on_delivery_enabled": True,
        "card_payment_enabled": True,
        "online_payment_enabled": False,
        "wallet_payment_enabled": False,
        "default_payment_method": BranchPaymentMethod.CARD,
        "marketplace_visible": True,
        "reservations_enabled": False,
        "max_capacity": 50,
        "currency": "USD",
    }
    defaults.update(overrides)
    return Branch.objects.create(**defaults)


LEGACY_CHECKOUT_FIELDS = (
    "deliveryEnabled",
    "pickupEnabled",
    "tableOrderingEnabled",
    "orderingEnabled",
    "deliveryRadius",
    "minimumOrder",
    "defaultOrderType",
    "cashPaymentEnabled",
    "cardPaymentEnabled",
    "onlinePaymentEnabled",
    "walletPaymentEnabled",
    "cashOnDeliveryEnabled",
    "defaultPaymentMethod",
    "sameDayDeliveryEnabled",
    "scheduledDeliveryEnabled",
    "contactlessDeliveryEnabled",
    "marketplaceVisible",
    "reservationsEnabled",
    "maxCapacity",
)


class BranchResponseSerializerCheckoutTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.data = BranchResponseSerializer(self.branch).data

    def test_checkout_object_exists(self):
        self.assertIn("checkout", self.data)
        self.assertIsInstance(self.data["checkout"], dict)

    def test_checkout_ordering_enabled_maps_from_typed_field(self):
        self.assertEqual(
            self.data["checkout"]["orderingEnabled"],
            self.branch.ordering_enabled,
        )

    def test_checkout_order_types_maps_from_typed_fields(self):
        order_types = self.data["checkout"]["orderTypes"]
        self.assertEqual(order_types["delivery"], self.branch.delivery_enabled)
        self.assertEqual(order_types["pickup"], self.branch.pickup_enabled)
        self.assertEqual(order_types["dineIn"], self.branch.table_ordering_enabled)
        self.assertEqual(order_types["default"], self.branch.default_order_type)

    def test_checkout_payments_maps_from_typed_fields(self):
        payments = self.data["checkout"]["payments"]
        self.assertEqual(payments["cash"], self.branch.cash_payment_enabled)
        self.assertEqual(payments["cashOnDelivery"], self.branch.cash_on_delivery_enabled)
        self.assertEqual(payments["card"], self.branch.card_payment_enabled)
        self.assertEqual(payments["online"], self.branch.online_payment_enabled)
        self.assertEqual(payments["wallet"], self.branch.wallet_payment_enabled)
        self.assertEqual(payments["default"], self.branch.default_payment_method)

    def test_checkout_delivery_maps_from_typed_fields(self):
        delivery = self.data["checkout"]["delivery"]
        self.assertEqual(delivery["radius"], self.branch.delivery_radius_km)
        self.assertEqual(
            Decimal(str(delivery["minimumOrder"])),
            self.branch.minimum_order_amount,
        )
        self.assertEqual(delivery["sameDay"], self.branch.same_day_delivery_enabled)
        self.assertEqual(delivery["scheduled"], self.branch.scheduled_delivery_enabled)
        self.assertEqual(delivery["contactless"], self.branch.contactless_delivery_enabled)

    def test_checkout_preserves_camel_case_keys(self):
        checkout = self.data["checkout"]
        self.assertIn("orderingEnabled", checkout)
        self.assertEqual(
            set(checkout["orderTypes"].keys()),
            {"delivery", "pickup", "dineIn", "default"},
        )
        self.assertEqual(
            set(checkout["payments"].keys()),
            {"cash", "cashOnDelivery", "card", "online", "wallet", "default"},
        )
        self.assertEqual(
            set(checkout["delivery"].keys()),
            {"radius", "minimumOrder", "sameDay", "scheduled", "contactless"},
        )

    def test_checkout_matches_example_contract(self):
        checkout = self.data["checkout"]
        self.assertTrue(checkout["orderingEnabled"])
        self.assertTrue(checkout["orderTypes"]["delivery"])
        self.assertTrue(checkout["orderTypes"]["pickup"])
        self.assertFalse(checkout["orderTypes"]["dineIn"])
        self.assertEqual(checkout["orderTypes"]["default"], "delivery")
        self.assertTrue(checkout["payments"]["cash"])
        self.assertTrue(checkout["payments"]["cashOnDelivery"])
        self.assertTrue(checkout["payments"]["card"])
        self.assertFalse(checkout["payments"]["online"])
        self.assertFalse(checkout["payments"]["wallet"])
        self.assertEqual(checkout["payments"]["default"], "card")
        self.assertEqual(checkout["delivery"]["radius"], 10)
        self.assertEqual(str(checkout["delivery"]["minimumOrder"]), "20.00")
        self.assertFalse(checkout["delivery"]["sameDay"])
        self.assertTrue(checkout["delivery"]["scheduled"])
        self.assertFalse(checkout["delivery"]["contactless"])

    def test_legacy_top_level_checkout_fields_remain(self):
        for field in LEGACY_CHECKOUT_FIELDS:
            self.assertIn(field, self.data)

    def test_legacy_top_level_fields_match_typed_branch_columns(self):
        self.assertEqual(self.data["deliveryEnabled"], self.branch.delivery_enabled)
        self.assertEqual(self.data["pickupEnabled"], self.branch.pickup_enabled)
        self.assertEqual(self.data["tableOrderingEnabled"], self.branch.table_ordering_enabled)
        self.assertEqual(self.data["orderingEnabled"], self.branch.ordering_enabled)
        self.assertEqual(self.data["deliveryRadius"], self.branch.delivery_radius_km)
        self.assertEqual(
            Decimal(str(self.data["minimumOrder"])),
            self.branch.minimum_order_amount,
        )
        self.assertEqual(self.data["defaultOrderType"], self.branch.default_order_type)
        self.assertEqual(self.data["cashPaymentEnabled"], self.branch.cash_payment_enabled)
        self.assertEqual(self.data["cardPaymentEnabled"], self.branch.card_payment_enabled)
        self.assertEqual(self.data["onlinePaymentEnabled"], self.branch.online_payment_enabled)
        self.assertEqual(self.data["walletPaymentEnabled"], self.branch.wallet_payment_enabled)
        self.assertEqual(
            self.data["cashOnDeliveryEnabled"],
            self.branch.cash_on_delivery_enabled,
        )
        self.assertEqual(self.data["defaultPaymentMethod"], self.branch.default_payment_method)
        self.assertEqual(
            self.data["sameDayDeliveryEnabled"],
            self.branch.same_day_delivery_enabled,
        )
        self.assertEqual(
            self.data["scheduledDeliveryEnabled"],
            self.branch.scheduled_delivery_enabled,
        )
        self.assertEqual(
            self.data["contactlessDeliveryEnabled"],
            self.branch.contactless_delivery_enabled,
        )
        self.assertEqual(self.data["marketplaceVisible"], self.branch.marketplace_visible)
        self.assertEqual(self.data["reservationsEnabled"], self.branch.reservations_enabled)
        self.assertEqual(self.data["maxCapacity"], self.branch.max_capacity)

    def test_checkout_reflects_nullable_defaults(self):
        branch = make_branch(
            default_order_type=None,
            default_payment_method=None,
            delivery_radius_km=None,
            minimum_order_amount=None,
        )
        data = BranchResponseSerializer(branch).data
        checkout = data["checkout"]

        self.assertIsNone(checkout["orderTypes"]["default"])
        self.assertIsNone(checkout["payments"]["default"])
        self.assertIsNone(checkout["delivery"]["radius"])
        self.assertIsNone(checkout["delivery"]["minimumOrder"])
