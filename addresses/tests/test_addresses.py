"""Tests for enterprise address subsystem."""

import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from addresses.domain.events import AddressEventBus
from addresses.models import Address, AddressAuditLog, AddressType
from addresses.services.address_domain_service import AddressDomainService
from menu.models import MenuCategory, MenuItem
from orders.models import Order, OrderDeliveryAddress, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant


def make_user(**kwargs):
    user = User(
        id=uuid.uuid4(),
        phone_number=kwargs.get("phone_number", f"+1555{uuid.uuid4().int % 10**7:07d}"),
        country_code=kwargs.get("country_code", "+1"),
        email=kwargs.get("email", f"{uuid.uuid4().hex}@example.com"),
        first_name=kwargs.get("first_name", "Jane"),
        last_name=kwargs.get("last_name", "Doe"),
    )
    user.set_password("testpass123")
    user.save()
    return user


def auth_client(user):
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def make_branch(*, delivery_enabled=True, delivery_radius=50):
    owner = Owner.objects.create(user=make_user())
    tenant = Tenant.objects.create(owner=owner, name=f"Tenant {uuid.uuid4().hex[:6]}")
    branch = Branch.objects.create(
        tenant=tenant,
        name="Main",
        latitude=Decimal("34.050000"),
        longitude=Decimal("-118.250000"),
        delivery_enabled=delivery_enabled,
        delivery_radius_km=delivery_radius,
        pickup_enabled=True,
        ordering_enabled=True,
        marketplace_visible=True,
    )
    return branch


def make_menu_item(branch):
    category = MenuCategory.objects.create(branch=branch, name="Mains")
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name="Burger",
        price=Decimal("10.00"),
    )


def valid_address_payload(**overrides):
    """Minimal address payload — identity fields come from the authenticated user."""
    payload = {
        "address_type": AddressType.HOME,
        "country": "US",
        "province": "CA",
        "city": "Los Angeles",
        "street": "123 Main St",
        "postal_code": "90001",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "is_default": True,
    }
    payload.update(overrides)
    return payload


class AddressDomainServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.domain = AddressDomainService()
        self.events = []
        AddressEventBus.subscribe(self.events.append)

    def test_formatted_address_generated_on_create(self):
        address = self.domain.create(self.user, valid_address_payload())
        self.assertIn("123 Main St", address.formatted_address)
        self.assertIn("Los Angeles", address.formatted_address)

    def test_audit_log_on_create(self):
        address = self.domain.create(self.user, valid_address_payload(), actor=self.user)
        self.assertTrue(AddressAuditLog.objects.filter(address=address, action="create").exists())

    def test_domain_event_published_on_create(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.domain.create(self.user, valid_address_payload())
        self.assertTrue(any(e.name == "AddressCreated" for e in self.events))

    def test_soft_delete_is_idempotent_and_preserves_audit(self):
        address = self.domain.create(self.user, valid_address_payload(), actor=self.user)
        self.domain.delete(self.user, address.id, actor=self.user)
        self.domain.delete(self.user, address.id, actor=self.user)
        stored = Address.all_objects.get(pk=address.id)
        self.assertIsNotNone(stored.deleted_at)
        self.assertTrue(AddressAuditLog.objects.filter(address=stored).exists())
        self.assertFalse(Address.objects.filter(pk=address.id).exists())

    def test_address_admin_cannot_hard_delete(self):
        from addresses.admin.address import AddressAdmin, AddressAuditLogAdmin
        from addresses.models import AddressAuditLog as AuditModel

        request = type("R", (), {"user": self.user})()
        self.assertFalse(AddressAdmin(Address, None).has_delete_permission(request))
        self.assertFalse(AddressAuditLogAdmin(AuditModel, None).has_delete_permission(request))
        address = self.domain.create(self.user, valid_address_payload())
        self.domain.delete(self.user, address.id, actor=self.user)
        restored = self.domain.restore(self.user, address.id, actor=self.user)
        self.assertIsNone(restored.deleted_at)

    def test_other_type_requires_custom_label(self):
        with self.assertRaises(Exception):
            self.domain.create(
                self.user,
                valid_address_payload(address_type=AddressType.OTHER),
            )


class AddressAPITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)

    def test_search_by_street(self):
        self.client.post("/api/users/addresses/", valid_address_payload(street="Unique Elm Road"), format="json")
        response = self.client.get("/api/users/addresses/?search=Elm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_formatted_address_in_response(self):
        response = self.client.post("/api/users/addresses/", valid_address_payload(), format="json")
        self.assertIn("formatted_address", response.data)
        self.assertTrue(response.data["formatted_address"])

    def test_address_type_enum_in_response(self):
        response = self.client.post("/api/users/addresses/", valid_address_payload(), format="json")
        self.assertEqual(response.data["address_type"], AddressType.HOME)

    def test_restore_endpoint(self):
        created = self.client.post("/api/users/addresses/", valid_address_payload(), format="json")
        address_id = created.data["id"]
        self.client.delete(f"/api/users/addresses/{address_id}/")
        restore = self.client.post(f"/api/users/addresses/{address_id}/restore/")
        self.assertEqual(restore.status_code, 200)
        self.assertIsNotNone(Address.objects.get(pk=address_id))


class CheckoutSnapshotTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.item = make_menu_item(self.branch)

    def test_checkout_with_address_id_and_override(self):
        address = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(street="100 Base St", delivery_notes="Ring bell"),
            format="json",
        ).data
        order = self.client.post(
            "/api/orders/",
            {
                "branch_id": str(self.branch.id),
                "order_type": OrderType.DELIVERY,
                "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": str(self.item.id), "quantity": 1}],
                "delivery_address": {
                    "address_id": address["id"],
                    "delivery_notes": "Override note",
                    "floor": "3",
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        snapshot = OrderDeliveryAddress.objects.get(pk=order.data["delivery_address"]["id"])
        self.assertEqual(snapshot.delivery_notes, "Override note")
        self.assertEqual(snapshot.floor, "3")
        self.assertEqual(snapshot.street, "100 Base St")
        self.assertIsNotNone(snapshot.calculated_at)
        self.assertIsNotNone(snapshot.branch_id)

    def test_snapshot_metadata_fields(self):
        order = self.client.post(
            "/api/orders/",
            {
                "branch_id": str(self.branch.id),
                "order_type": OrderType.DELIVERY,
                "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": str(self.item.id), "quantity": 1}],
                "delivery_address": {
                    "street": "200 Delivery Ave",
                    "city": "Los Angeles",
                    "zip": "90001",
                    "lat": 34.0522,
                    "lng": -118.2437,
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        delivery = order.data["delivery_address"]
        self.assertIn("delivery_fee", delivery)
        self.assertIn("distance_km", delivery)
        self.assertIn("estimated_delivery_time", delivery)
        self.assertIn("formatted_address", delivery)

    def test_out_of_zone_rejected(self):
        far_branch = make_branch(delivery_radius=1)
        item = make_menu_item(far_branch)
        order = self.client.post(
            "/api/orders/",
            {
                "branch_id": str(far_branch.id),
                "order_type": OrderType.DELIVERY,
                "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": str(item.id), "quantity": 1}],
                "delivery_address": {
                    "street": "Far Away",
                    "city": "San Francisco",
                    "zip": "94102",
                    "lat": 37.7749,
                    "lng": -122.4194,
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 400)
        self.assertEqual(order.data["error"]["code"], "address_not_serviceable")
