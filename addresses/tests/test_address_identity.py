"""Tests for server-side user identity injection on address create/update."""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from addresses.domain.address_type import AddressType
from addresses.services.address_domain_service import AddressDomainService
from addresses.tests.test_addresses import (
    auth_client,
    make_branch,
    make_menu_item,
    make_user,
    valid_address_payload,
)
from orders.models import OrderDeliveryAddress, OrderType, PaymentMethod


class AddressIdentityDomainTests(TestCase):
    def setUp(self):
        self.user = make_user(
            first_name="Jane",
            last_name="Doe",
            country_code="+1",
            phone_number="+15559123456",
        )
        self.domain = AddressDomainService()
        self.expected_phone = "5559123456"

    def test_create_without_identity_fields(self):
        address = self.domain.create(self.user, valid_address_payload())
        self.assertEqual(address.first_name, "Jane")
        self.assertEqual(address.last_name, "Doe")
        self.assertEqual(address.country_code, "+1")
        self.assertEqual(address.phone, self.expected_phone)
        self.assertEqual(address.title, "Home")

    def test_ignores_spoofed_first_name(self):
        address = self.domain.create(
            self.user,
            valid_address_payload(first_name="Evil", last_name="Hacker", country_code="+44"),
        )
        self.assertEqual(address.first_name, "Jane")
        self.assertEqual(address.last_name, "Doe")
        self.assertEqual(address.country_code, "+1")

    def test_ignores_spoofed_phone(self):
        address = self.domain.create(
            self.user,
            valid_address_payload(phone="9999999999"),
        )
        self.assertEqual(address.phone, self.expected_phone)

    def test_title_derived_from_address_type(self):
        address = self.domain.create(
            self.user,
            valid_address_payload(address_type=AddressType.WORK, title="Ignored"),
        )
        self.assertEqual(address.title, "Work")
        self.assertEqual(address.address_type, AddressType.WORK)

    def test_incomplete_profile_rejected(self):
        incomplete = make_user(
            first_name="",
            last_name="",
            phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        )
        with self.assertRaises(Exception) as ctx:
            self.domain.create(incomplete, valid_address_payload())
        self.assertIn("profile", str(ctx.exception))

    def test_update_refreshes_identity_from_user(self):
        address = self.domain.create(self.user, valid_address_payload())
        self.user.first_name = "Janet"
        self.user.last_name = "Smith"
        self.user.country_code = "+44"
        self.user.phone_number = "+449123456789"
        self.user.save(update_fields=["first_name", "last_name", "country_code", "phone_number"])

        updated = self.domain.update(
            self.user,
            address.id,
            {"street": "456 Oak Ave"},
        )
        self.assertEqual(updated.street, "456 Oak Ave")
        self.assertEqual(updated.first_name, "Janet")
        self.assertEqual(updated.last_name, "Smith")
        self.assertEqual(updated.country_code, "+44")
        self.assertEqual(updated.phone, "9123456789")

    def test_update_ignores_spoofed_identity(self):
        address = self.domain.create(self.user, valid_address_payload())
        updated = self.domain.update(
            self.user,
            address.id,
            {
                "first_name": "Spoofed",
                "last_name": "Name",
                "country_code": "+99",
                "phone": "0000000000",
            },
        )
        self.assertEqual(updated.first_name, "Jane")
        self.assertEqual(updated.last_name, "Doe")
        self.assertEqual(updated.phone, self.expected_phone)

    def test_missing_profile_phone_rejected(self):
        no_phone = make_user(
            first_name="Jane",
            last_name="Doe",
            phone_number="",
        )
        no_phone.phone_number = None
        no_phone.save(update_fields=["phone_number"])
        with self.assertRaises(Exception) as ctx:
            self.domain.create(no_phone, valid_address_payload())
        self.assertIn("phone number", str(ctx.exception).lower())


class AddressIdentityAPITests(TestCase):
    def setUp(self):
        self.user = make_user(
            first_name="Jane",
            last_name="Doe",
            country_code="+1",
            phone_number="+15559123456",
        )
        self.client = auth_client(self.user)
        self.expected_phone = "5559123456"

    def test_create_without_identity_fields(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["first_name"], "Jane")
        self.assertEqual(response.data["last_name"], "Doe")
        self.assertEqual(response.data["country_code"], "+1")
        self.assertEqual(response.data["phone"], self.expected_phone)
        self.assertEqual(response.data["title"], "Home")

    def test_create_without_phone_field(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["phone"], self.expected_phone)

    def test_update_without_phone_field(self):
        created = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        response = self.client.patch(
            f"/api/users/addresses/{created.data['id']}/",
            {"street": "789 Pine Rd"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone"], self.expected_phone)

    def test_update_without_identity_fields(self):
        created = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        response = self.client.patch(
            f"/api/users/addresses/{created.data['id']}/",
            {"street": "789 Pine Rd"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["street"], "789 Pine Rd")
        self.assertEqual(response.data["first_name"], "Jane")

    def test_ignores_spoofed_first_name_on_create(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(first_name="Attacker"),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["first_name"], "Jane")

    def test_ignores_spoofed_last_name_on_create(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(last_name="Attacker"),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["last_name"], "Doe")

    def test_ignores_spoofed_country_code_on_create(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(country_code="+99"),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["country_code"], "+1")

    def test_ignores_spoofed_phone_on_create(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(phone="9999999999"),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["phone"], self.expected_phone)

    def test_missing_profile_phone_returns_validation_error(self):
        no_phone = User(
            id=uuid.uuid4(),
            phone_number=None,
            country_code="+1",
            email=f"{uuid.uuid4().hex}@example.com",
            first_name="Jane",
            last_name="Doe",
        )
        no_phone.set_password("testpass123")
        no_phone.save()

        client = APIClient()
        token = str(RefreshToken.for_user(no_phone).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data)
        self.assertTrue(
            any("phone number" in str(msg).lower() for msg in response.data["profile"])
        )

    def test_incomplete_profile_returns_validation_error(self):
        incomplete = User(
            id=uuid.uuid4(),
            phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
            country_code="+1",
            email=f"{uuid.uuid4().hex}@example.com",
            first_name="",
            last_name="",
        )
        incomplete.set_password("testpass123")
        incomplete.save()

        client = APIClient()
        token = str(RefreshToken.for_user(incomplete).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data)


class CheckoutSnapshotPhoneTests(TestCase):
    def setUp(self):
        self.user = make_user(
            first_name="Jane",
            last_name="Doe",
            country_code="+1",
            phone_number="+15559123456",
        )
        self.client = auth_client(self.user)
        self.branch = make_branch()
        self.item = make_menu_item(self.branch)
        self.expected_phone = "5559123456"

    def test_snapshot_uses_authenticated_user_phone_from_address_id(self):
        address = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
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
                    "phone": "0000000000",
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        snapshot = OrderDeliveryAddress.objects.get(pk=order.data["delivery_address"]["id"])
        self.assertEqual(snapshot.phone, self.expected_phone)

    def test_snapshot_uses_authenticated_user_phone_inline(self):
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
                    "phone": "0000000000",
                },
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        snapshot = OrderDeliveryAddress.objects.get(pk=order.data["delivery_address"]["id"])
        self.assertEqual(snapshot.phone, self.expected_phone)
