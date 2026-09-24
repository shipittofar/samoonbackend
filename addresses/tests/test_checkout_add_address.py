"""Checkout add-address contract: legacy field names, integer id, failures."""

import uuid
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from addresses.models import Address
from addresses.tests.test_addresses import auth_client, make_user


CHECKOUT_PAYLOAD = {
    "label": "Home",
    "street": "500 Checkout Ave",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90001",
    "lat": 34.05,
    "lng": -118.25,
    "is_default": True,
}


class CheckoutAddAddressTests(TestCase):
    def setUp(self):
        self.user = make_user(first_name="Jane", last_name="Doe", country_code="+1")
        self.other = make_user(first_name="Other", last_name="User", country_code="+1")
        self.client = auth_client(self.user)

    def test_legacy_checkout_create_returns_positive_integer_id(self):
        response = self.client.post("/api/orders/addresses/", CHECKOUT_PAYLOAD, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsInstance(response.data["id"], int)
        self.assertGreater(response.data["id"], 0)
        self.assertEqual(response.data["street"], "500 Checkout Ave")
        self.assertEqual(response.data["city"], "Los Angeles")
        self.assertEqual(response.data["state"], "CA")
        self.assertEqual(response.data["zip"], "90001")
        self.assertEqual(response.data["label"], "Home")
        self.assertTrue(response.data["is_default"])
        self.assertIn("formatted_address", response.data)

        stored = Address.objects.get(legacy_id=response.data["id"])
        self.assertEqual(stored.user_id, self.user.id)
        self.assertNotEqual(stored.user_id, self.other.id)

        detail = self.client.get(f"/api/orders/addresses/{response.data['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["street"], "500 Checkout Ave")

    def test_users_endpoint_accepts_checkout_field_names(self):
        response = self.client.post("/api/users/addresses/", CHECKOUT_PAYLOAD, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["street"], "500 Checkout Ave")
        self.assertEqual(response.data["province"], "CA")
        self.assertEqual(response.data["postal_code"], "90001")
        self.assertEqual(response.data["address_type"], "home")
        self.assertEqual(response.data["first_name"], "Jane")
        stored = Address.objects.get(pk=response.data["id"])
        self.assertEqual(stored.user_id, self.user.id)

    def test_missing_street_is_400(self):
        payload = dict(CHECKOUT_PAYLOAD)
        payload.pop("street")
        response = self.client.post("/api/orders/addresses/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_is_401(self):
        response = APIClient().post("/api/orders/addresses/", CHECKOUT_PAYLOAD, format="json")
        self.assertEqual(response.status_code, 401)
        response = APIClient().post("/api/users/addresses/", CHECKOUT_PAYLOAD, format="json")
        self.assertEqual(response.status_code, 401)

    def test_cannot_attach_address_to_another_user(self):
        payload = dict(CHECKOUT_PAYLOAD)
        payload["user"] = str(self.other.id)
        payload["user_id"] = str(self.other.id)
        response = self.client.post("/api/users/addresses/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        stored = Address.objects.get(pk=response.data["id"])
        self.assertEqual(stored.user_id, self.user.id)

    def test_other_user_cannot_read_created_address(self):
        created = self.client.post("/api/orders/addresses/", CHECKOUT_PAYLOAD, format="json")
        other_client = auth_client(self.other)
        response = other_client.get(f"/api/orders/addresses/{created.data['id']}/")
        self.assertEqual(response.status_code, 404)

    def test_database_failure_returns_structured_error(self):
        with patch(
            "addresses.services.address_domain_service.AddressDataAccessLayer.create_address",
            side_effect=IntegrityError("insert failed"),
        ):
            response = self.client.post("/api/users/addresses/", CHECKOUT_PAYLOAD, format="json")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["code"], "address_persist_failed")
        self.assertFalse(Address.objects.filter(user=self.user, street="500 Checkout Ave").exists())
