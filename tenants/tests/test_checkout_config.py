"""Unit tests for checkout config helpers."""

from django.test import SimpleTestCase

from tenants.checkout_config import flatten_nested_checkout


class FlattenNestedCheckoutTests(SimpleTestCase):
    def test_flattens_nested_frontend_checkout_object(self):
        flat = flatten_nested_checkout({
            "orderingEnabled": False,
            "orderTypes": {
                "delivery": True,
                "pickup": False,
                "dineIn": True,
                "default": "dineIn",
            },
            "payments": {
                "cash": False,
                "cashOnDelivery": True,
                "card": True,
                "online": False,
                "wallet": True,
                "default": "wallet",
            },
            "delivery": {
                "radius": 12,
                "minimumOrder": "18.00",
                "sameDay": True,
                "scheduled": False,
                "contactless": True,
            },
        })

        self.assertFalse(flat["orderingEnabled"])
        self.assertTrue(flat["deliveryEnabled"])
        self.assertFalse(flat["pickupEnabled"])
        self.assertTrue(flat["tableOrderingEnabled"])
        self.assertEqual(flat["defaultOrderType"], "dine_in")
        self.assertFalse(flat["cashPaymentEnabled"])
        self.assertTrue(flat["cashOnDeliveryEnabled"])
        self.assertEqual(flat["defaultPaymentMethod"], "wallet")
        self.assertEqual(flat["deliveryRadius"], 12)
        self.assertEqual(flat["minimumOrder"], "18.00")
