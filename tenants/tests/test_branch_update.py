"""API tests for PATCH /api/branches/{branch_id}/."""
import io
import json
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, Owner, Tenant, WorkingHour


UPDATE_URL = "/api/branches/{branch_id}/"


def _jpeg_bytes(color=(200, 100, 50), size=(8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()

FRONTEND_PAYLOAD = {
    "name": "Updated Branch",
    "slug": "ignored-slug",
    "description": "Updated description",
    "type": "physical",
    "location": {
        "address": "456 Oak Ave",
        "city": "Boston",
        "country": "US",
    },
    "contact": {
        "phone_number": "+15559876543",
        "email": "updated@example.com",
    },
    "businessHours": [
        {
            "day": "Wednesday",
            "open": "08:00",
            "close": "21:00",
            "isClosed": False,
        }
    ],
    "deliveryEnabled": True,
    "pickupEnabled": False,
    "tableOrderingEnabled": True,
    "orderingEnabled": True,
    "marketplaceVisible": False,
    "isDefault": True,
}


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


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {
        "tenant": tenant,
        "name": "Original Branch",
        "description": "Original description",
        "address": "123 Main",
        "city": "NYC",
        "country": "US",
        "delivery_enabled": False,
        "pickup_enabled": True,
        "marketplace_visible": True,
    }
    defaults.update(kwargs)
    return Branch.objects.create(**defaults)


class BranchConsoleUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        WorkingHour.objects.create(
            branch=self.branch,
            day=WorkingHour.Weekday.MONDAY,
            open_time="09:00",
            close_time="22:00",
            is_closed=False,
        )
        self.client.force_authenticate(user=self.owner_user)
        self.url = UPDATE_URL.format(branch_id=self.branch.id)

    def test_patch_updates_frontend_nested_payload(self):
        response = self.client.patch(self.url, FRONTEND_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["name"], "Updated Branch")
        self.assertEqual(data["description"], "Updated description")
        self.assertEqual(data["location"]["address"], "456 Oak Ave")
        self.assertEqual(data["location"]["city"], "Boston")
        self.assertEqual(data["contact"]["phone_number"], "+15559876543")
        self.assertEqual(data["contact"]["email"], "updated@example.com")
        self.assertEqual(len(data["businessHours"]), 1)
        self.assertEqual(data["businessHours"][0]["day"], "Wednesday")
        self.assertTrue(data["deliveryEnabled"])
        self.assertFalse(data["pickupEnabled"])
        self.assertTrue(data["tableOrderingEnabled"])
        self.assertFalse(data["marketplaceVisible"])
        self.assertTrue(data["isDefault"])
        self.assertNotEqual(data["slug"], "ignored-slug")

        self.branch.refresh_from_db()
        self.assertEqual(self.branch.description, "Updated description")
        self.assertEqual(self.branch.address, "456 Oak Ave")
        self.assertTrue(self.branch.delivery_enabled)
        self.assertFalse(self.branch.pickup_enabled)
        self.assertEqual(self.branch.working_hours.count(), 1)

    def test_patch_multipart_with_json_string_fields(self):
        payload = {
            "name": "Multipart Branch",
            "location": json.dumps({
                "address": "789 Pine Rd",
                "city": "Austin",
                "country": "US",
            }),
            "contact": json.dumps({
                "phone_number": "+15551112222",
                "email": "multipart@example.com",
            }),
            "businessHours": json.dumps([
                {
                    "day": "Friday",
                    "open": "10:00",
                    "close": "20:00",
                    "isClosed": False,
                }
            ]),
            "deliveryEnabled": "true",
            "pickupEnabled": "false",
        }

        response = self.client.patch(self.url, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "Multipart Branch")
        self.assertEqual(data["location"]["address"], "789 Pine Rd")
        self.assertEqual(data["contact"]["email"], "multipart@example.com")
        self.assertEqual(data["businessHours"][0]["day"], "Friday")
        self.assertTrue(data["deliveryEnabled"])
        self.assertFalse(data["pickupEnabled"])

    def test_patch_nested_checkout_object(self):
        payload = {
            "checkout": json.dumps({
                "orderingEnabled": False,
                "orderTypes": {
                    "delivery": True,
                    "pickup": False,
                    "dineIn": True,
                    "default": "dineIn",
                },
                "payments": {
                    "cash": False,
                    "card": True,
                    "default": "card",
                },
                "delivery": {
                    "radius": 15,
                    "minimumOrder": "25.50",
                    "sameDay": True,
                    "scheduled": False,
                    "contactless": True,
                },
            }),
        }

        response = self.client.patch(self.url, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["orderingEnabled"])
        self.assertTrue(data["deliveryEnabled"])
        self.assertFalse(data["pickupEnabled"])
        self.assertTrue(data["tableOrderingEnabled"])
        self.assertEqual(data["defaultOrderType"], "dine_in")
        self.assertFalse(data["cashPaymentEnabled"])
        self.assertTrue(data["cardPaymentEnabled"])
        self.assertEqual(data["defaultPaymentMethod"], "card")
        self.assertEqual(data["deliveryRadius"], 15)
        self.assertEqual(str(data["minimumOrder"]), "25.50")
        self.assertTrue(data["sameDayDeliveryEnabled"])
        self.assertFalse(data["scheduledDeliveryEnabled"])
        self.assertTrue(data["contactlessDeliveryEnabled"])

    def test_patch_empty_image_string_clears_image(self):
        self.branch.image = SimpleUploadedFile(
            "branch.jpg", _jpeg_bytes(), content_type="image/jpeg",
        )
        self.branch.save(update_fields=["image"])
        self.assertTrue(self.branch.image)

        response = self.client.patch(
            self.url,
            {"image": ""},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.image)

    def test_patch_empty_cover_image_string_clears_cover_image(self):
        self.branch.cover_image = SimpleUploadedFile(
            "cover.jpg", _jpeg_bytes(color=(50, 100, 200)), content_type="image/jpeg",
        )
        self.branch.save(update_fields=["cover_image"])
        self.assertTrue(self.branch.cover_image)

        response = self.client.patch(
            self.url,
            {"coverImage": ""},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.cover_image)

    def test_patch_partial_update_preserves_unsent_fields(self):
        original_name = self.branch.name
        original_city = self.branch.city

        response = self.client.patch(
            self.url,
            {"description": "Only description changed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, original_name)
        self.assertEqual(self.branch.city, original_city)
        self.assertEqual(self.branch.description, "Only description changed")

    def test_patch_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.patch(self.url, FRONTEND_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_denies_non_owner(self):
        other_user = make_user()
        self.client.force_authenticate(user=other_user)
        response = self.client.patch(self.url, FRONTEND_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_unknown_branch_returns_not_found(self):
        unknown_url = UPDATE_URL.format(branch_id=uuid.uuid4())
        response = self.client.patch(unknown_url, FRONTEND_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
