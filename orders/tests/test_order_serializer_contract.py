"""Regression tests: order API responses must expose UUID public identifiers,
not integer-coerced UUID bit patterns."""
import uuid
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from menu.models import Extra, MenuCategory, MenuItem, MenuItemExtra
from orders.api.serializers.response import OrderResponseSerializer
from orders.models import Order, OrderItem, OrderItemExtra, OrderStatus, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant


def _uuid_str(value) -> str:
    return str(value)


def _make_user():
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


class OrderSerializerContractTests(TestCase):
    def setUp(self):
        owner = Owner.objects.create(user=_make_user())
        self.tenant = Tenant.objects.create(
            owner=owner,
            name=f"Tenant {uuid.uuid4().hex[:6]}",
        )
        self.branch = Branch.objects.create(tenant=self.tenant, name="Main")
        self.category = MenuCategory.objects.create(branch=self.branch, name="Mains")
        self.menu_item = MenuItem.objects.create(
            branch=self.branch,
            category=self.category,
            name="Burger",
            price=Decimal("10.00"),
        )
        self.extra = Extra.objects.create(
            branch=self.branch,
            name="Cheese",
            price=Decimal("1.50"),
        )
        MenuItemExtra.objects.create(item=self.menu_item, extra=self.extra)

        self.order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
            status=OrderStatus.PENDING,
            subtotal=Decimal("11.50"),
            total=Decimal("11.50"),
        )
        order_item = OrderItem.objects.create(
            order=self.order,
            menu_item=self.menu_item,
            name=self.menu_item.name,
            quantity=1,
            unit_price=Decimal("10.00"),
            total_price=Decimal("11.50"),
        )
        OrderItemExtra.objects.create(
            order_item=order_item,
            extra=self.extra,
            price=Decimal("1.50"),
        )

    def _assert_public_uuid_string(self, value, expected):
        self.assertIsInstance(value, str)
        self.assertEqual(value, _uuid_str(expected))
        self.assertRegex(value, r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def test_order_response_serializes_public_uuids(self):
        order = (
            Order.objects
            .select_related("branch", "branch__tenant")
            .prefetch_related("items__menu_item", "items__extras__extra")
            .get(pk=self.order.pk)
        )

        data = OrderResponseSerializer(order).data

        self._assert_public_uuid_string(data["id"], self.order.id)
        self._assert_public_uuid_string(data["branch_id"], self.branch.id)
        self._assert_public_uuid_string(data["tenant_id"], self.tenant.id)
        self.assertEqual(data["branch_slug"], self.branch.slug)
        self.assertEqual(data["tenant_slug"], self.tenant.slug)
        self.assertIn("tenant_is_active", data)
        self.assertIn("tenant_status", data)
        self.assertIn("tenant", data)
        self.assertEqual(data["tenant"]["id"], _uuid_str(self.tenant.id))
        self.assertEqual(data["tenant"]["status"], self.tenant.status)

        item = data["items"][0]
        self.assertNotIn("id", item)
        self._assert_public_uuid_string(item["menu_item_id"], self.menu_item.id)

        extra = item["extras"][0]
        self._assert_public_uuid_string(extra["extra_id"], self.extra.id)

    def test_uuid_fields_are_not_integer_coerced_bit_patterns(self):
        """IntegerField on UUID sources produces huge bogus integers — guard."""
        data = OrderResponseSerializer(
            Order.objects
            .select_related("branch", "branch__tenant")
            .prefetch_related("items__menu_item", "items__extras__extra")
            .get(pk=self.order.pk)
        ).data

        for key in ("branch_id", "tenant_id"):
            self.assertIsInstance(data[key], str)
            self.assertLess(len(data[key]), 40)

        menu_item_id = data["items"][0]["menu_item_id"]
        self.assertIsInstance(menu_item_id, str)
        self.assertLess(len(menu_item_id), 40)

        extra_id = data["items"][0]["extras"][0]["extra_id"]
        self.assertIsInstance(extra_id, str)
        self.assertLess(len(extra_id), 40)
